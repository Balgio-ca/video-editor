"""Ce qui change d'une machine à l'autre : encodeur vidéo, transcription, outils de l'environnement.

macOS (puce Apple)  encodeur h264_videotoolbox, transcription mlx-whisper
Linux, Windows      encodeur h264_nvenc si une carte NVIDIA répond, sinon libx264 ;
                    transcription faster-whisper (CUDA si disponible, sinon processeur)

Réglages par variable d'environnement :
  VIDEO_ENCODER    videotoolbox, nvenc ou x264 (force l'encodeur)
  WHISPER_BACKEND  mlx ou faster (force la transcription)
  WHISPER_MODEL    modèle Whisper (défaut : large-v3-turbo)
  WHISPER_DEVICE   cpu, cuda ou auto pour faster-whisper (défaut : auto)
"""
from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
# sous Windows, Python lit les fichiers en cp1252 par défaut : on relance en mode UTF-8 (accents des JSON)
if WINDOWS and not sys.flags.utf8_mode and os.environ.get("PYTHONUTF8") != "1":
    os.environ["PYTHONUTF8"] = "1"
    os.execv(sys.executable, [sys.executable, "-X", "utf8", *sys.argv])
MAC_ARM = sys.platform == "darwin" and platform.machine() == "arm64"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3-turbo")


# ------------------------------------------------------------------ outils de l'environnement
def outil(nom: str) -> str:
    """Chemin d'un exécutable installé dans le .venv (auto-editor...), sinon celui du PATH."""
    venv_bin = Path(sys.executable).parent
    for cand in (venv_bin / nom, venv_bin / f"{nom}.exe"):
        if cand.exists():
            return str(cand)
    trouve = shutil.which(nom)
    if not trouve:
        raise SystemExit(f"« {nom} » introuvable : installer les dépendances (voir README)")
    return trouve


# ------------------------------------------------------------------ encodeur vidéo
@functools.lru_cache(maxsize=1)
def encodeur() -> str:
    force = os.environ.get("VIDEO_ENCODER", "").lower()
    if force in ("videotoolbox", "nvenc", "x264"):
        return force
    if sys.platform == "darwin":
        return "videotoolbox"
    # NVENC n'est retenu que s'il encode vraiment (pilote présent, carte compatible)
    test = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                           "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True)
    return "nvenc" if test.returncode == 0 else "x264"


def h264(debit: str) -> list[str]:
    """Arguments FFmpeg d'un encodage H.264 au débit visé (ex. « 12M »), selon la machine."""
    enc = encodeur()
    if enc == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", debit]
    if enc == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-b:v", debit]
    mega = float(debit.rstrip("Mm"))
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-maxrate", debit, "-bufsize", f"{mega * 2:g}M"]


# ------------------------------------------------------------------ transcription
def moteur_whisper() -> str:
    force = os.environ.get("WHISPER_BACKEND", "").lower()
    if force in ("mlx", "faster"):
        return force
    return "mlx" if MAC_ARM else "faster"


@functools.lru_cache(maxsize=1)
def _faster_model():
    from faster_whisper import WhisperModel

    device = os.environ.get("WHISPER_DEVICE", "auto")
    return WhisperModel(WHISPER_MODEL, device=device, compute_type="auto")


def transcrire(wav: str | Path, langue: str, prompt: str | None = None, mots: bool = True) -> dict:
    """Transcription au format mlx-whisper : {"text": ..., "segments": [{"words": [{"word", "start", "end"}]}]}."""
    if moteur_whisper() == "mlx":
        import mlx_whisper

        return mlx_whisper.transcribe(str(wav), path_or_hf_repo=f"mlx-community/whisper-{WHISPER_MODEL}",
                                      language=langue, word_timestamps=mots, initial_prompt=prompt,
                                      condition_on_previous_text=False)
    # le son est décodé par FFmpeg plutôt que par PyAV (dont l'API change d'une version à l'autre)
    import numpy as np

    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    segs, _ = _faster_model().transcribe(audio, language=langue, word_timestamps=mots, initial_prompt=prompt,
                                         condition_on_previous_text=False, vad_filter=False)
    segments = [{"text": s.text, "start": float(s.start), "end": float(s.end),
                 "words": [{"word": w.word, "start": float(w.start), "end": float(w.end)} for w in (s.words or [])]} for s in segs]
    return {"text": "".join(s["text"] for s in segments), "segments": segments}


# ------------------------------------------------------------------ rendu HyperFrames (Node 22)
def commande_hyperframes(args: str, dossier: Path) -> tuple[list[str] | str, dict]:
    """Commande pour lancer `npx hyperframes <args>` dans `dossier`, avec un Node 22 trouvé au PATH ou par nvm."""
    def version_node() -> int:
        try:
            v = subprocess.run(["node", "--version"], capture_output=True, text=True, shell=WINDOWS).stdout.strip()
            return int(v.lstrip("v").split(".")[0])
        except (OSError, ValueError):
            return 0

    if version_node() >= 22:
        return (f"npx hyperframes {args}" if WINDOWS else ["bash", "-c", f'cd "{dossier}" && npx hyperframes {args}']), {"shell": WINDOWS, "cwd": dossier}
    nvm = Path.home() / ".nvm" / "nvm.sh"
    if not WINDOWS and nvm.exists():
        return ["bash", "-lc", f'source "{nvm}" && nvm use 22 >/dev/null && cd "{dossier}" && npx hyperframes {args}'], {}
    raise SystemExit("HyperFrames demande Node.js 22 ou plus : installer Node 22 (voir README)")


# ------------------------------------------------------------------ fichier .env
def charger_env(fichier: Path | None = None) -> None:
    """Charge les clés de .env (à la racine du dépôt) sans écraser les variables déjà définies."""
    fichier = fichier or Path(__file__).resolve().parent.parent / ".env"
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, val = ligne.split("=", 1)
        val = val.strip().strip('"').strip("'")
        if val and cle.strip() not in os.environ:
            os.environ[cle.strip()] = val


charger_env()
