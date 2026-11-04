#!/usr/bin/env python3
"""Vérifie que la machine a tout ce qu'il faut pour monter un reel, et dit quoi faire sinon.

  diagnostic.py            tous les points, plus un essai d'encodage FFmpeg de 0,2 s
  diagnostic.py --rapide   sans l'essai d'encodage ni le chargement du module Whisper

Chaque point sort en OK, À FAIRE (obligatoire) ou FACULTATIF, avec la commande qui corrige
selon le système (brew, apt, winget). Aucune requête réseau n'est faite et aucune clé n'est affichée.
Code de sortie : 0 si tout l'obligatoire est OK, 1 sinon.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plateforme  # noqa: E402  (charge .env)
from plateforme import MAC_ARM, WINDOWS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAC = sys.platform == "darwin"
VENV_PY = r".venv\Scripts\python.exe" if WINDOWS else ".venv/bin/python"
INSTALLER_DEPS = f"uv pip install --python {VENV_PY} -r requirements.txt"
FILTRES = ("lut3d", "loudnorm", "sidechaincompress")

OK, A_FAIRE, FACULTATIF = "OK", "À FAIRE", "FACULTATIF"
resultats: list[tuple[str, str, str]] = []


def note(statut: str, texte: str, correction: str = "") -> None:
    resultats.append((statut, texte, correction))
    print(f"  {statut:<11}{texte}")
    if correction and statut != OK:
        for ligne in correction.splitlines():
            print(f"  {'':<11}  {ligne}")


def selon(mac: str, linux: str, windows: str) -> str:
    return windows if WINDOWS else mac if MAC else linux


def lancer(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None


def copier_cmd(source: str, cible: str) -> str:
    return f"copy {source.replace('/', chr(92))} {cible.replace('/', chr(92))}" if WINDOWS else f"cp {source} {cible}"


# ------------------------------------------------------------------ Python
def verifier_python() -> bool:
    v = sys.version_info
    venv = ROOT / ".venv"
    if v < (3, 12):
        note(A_FAIRE, f"Python {v.major}.{v.minor} : il faut 3.12 ou plus",
             f"uv venv --python 3.12 .venv\n{INSTALLER_DEPS}")
    else:
        note(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    dans_venv = Path(sys.prefix).resolve() == venv.resolve()
    if dans_venv:
        note(OK, "lancé depuis le .venv du dépôt")
    elif venv.exists():
        note(A_FAIRE, f"lancé avec {sys.executable}, pas avec le .venv du dépôt",
             f"{VENV_PY} pipeline/diagnostic.py")
    else:
        note(A_FAIRE, ".venv absent à la racine du dépôt", f"uv venv --python 3.12 .venv\n{INSTALLER_DEPS}")
    return dans_venv


def verifier_modules() -> None:
    noms = {"requests": "requests", "PIL": "pillow", "numpy": "numpy", "cv2": "opencv-python-headless"}
    manquants = [paquet for module, paquet in noms.items() if importlib.util.find_spec(module) is None]
    if manquants:
        note(A_FAIRE, f"modules Python absents : {', '.join(manquants)}", INSTALLER_DEPS)
    else:
        note(OK, "modules Python : requests, pillow, numpy, opencv")


# ------------------------------------------------------------------ FFmpeg
def version_ffmpeg(sortie: str) -> tuple[int | None, str]:
    """(version majeure, texte) ; None pour une version de développement (git), toujours récente."""
    m = re.search(r"version\s+(\S+)", sortie)
    brut = m.group(1) if m else "?"
    n = re.match(r"n?(\d+)\.(\d+)", brut)
    if n:
        return int(n.group(1)), brut
    return None, brut


def verifier_ffmpeg() -> bool:
    corr = selon("brew install ffmpeg",
                 "sudo apt install -y ffmpeg   (Ubuntu 24.04 ou plus ; sinon une version statique récente)",
                 "winget install Gyan.FFmpeg")
    maj = selon("brew upgrade ffmpeg", corr, "winget upgrade Gyan.FFmpeg")
    absents = [n for n in ("ffmpeg", "ffprobe") if not shutil.which(n)]
    if absents:
        note(A_FAIRE, f"{' et '.join(absents)} introuvable{'s' if len(absents) > 1 else ''} au PATH", corr)
        return False
    r = lancer(["ffmpeg", "-hide_banner", "-version"])
    majeure, texte = version_ffmpeg(r.stdout if r else "")
    if majeure is not None and majeure < 6:
        note(A_FAIRE, f"FFmpeg {texte} : il faut la version 6 ou plus", maj)
        return False
    note(OK, f"FFmpeg {texte}{' (version de développement)' if majeure is None else ''} et ffprobe")

    r = lancer(["ffmpeg", "-hide_banner", "-filters"])
    presents = {ligne.split()[1] for ligne in (r.stdout if r else "").splitlines() if len(ligne.split()) > 2}
    manquants = [f for f in FILTRES if f not in presents]
    if manquants:
        note(A_FAIRE, f"filtres FFmpeg absents : {', '.join(manquants)}",
             selon("brew reinstall ffmpeg", "installer une version complète de FFmpeg (apt ou version statique)",
                   "winget install Gyan.FFmpeg   (version « full »)"))
        return False
    note(OK, f"filtres FFmpeg : {', '.join(FILTRES)}")
    return True


def verifier_encodeur() -> bool:
    enc = plateforme.encodeur()
    codec = {"videotoolbox": "h264_videotoolbox", "nvenc": "h264_nvenc", "x264": "libx264"}[enc]
    r = lancer(["ffmpeg", "-hide_banner", "-encoders"])
    if codec not in (r.stdout if r else ""):
        force = os.environ.get("VIDEO_ENCODER")
        note(A_FAIRE, f"encodeur {codec} absent de FFmpeg" + (f" (VIDEO_ENCODER={force})" if force else ""),
             "retirer VIDEO_ENCODER de .env (ou de l'environnement)" if force else
             selon("brew reinstall ffmpeg", "sudo apt install -y ffmpeg   (avec libx264)", "winget install Gyan.FFmpeg"))
        return False
    note(OK, f"encodeur vidéo : {codec}")
    return True


def essai_encodage() -> None:
    lut = ROOT / "pipeline" / "luts" / "slog3-sgamut3-to-rec709.cube"
    with tempfile.TemporaryDirectory() as tmp:
        sortie = Path(tmp) / "essai.mp4"
        filtre_v = "format=yuv420p"
        if lut.exists():
            # lut3d lit le chemin dans le graphe de filtres : on travaille dans le dossier de la LUT
            filtre_v = f"lut3d={lut.name},format=yuv420p"
        cmd = ["ffmpeg", "-v", "error", "-y",
               "-f", "lavfi", "-i", "testsrc2=s=320x576:r=30:d=0.2",
               "-f", "lavfi", "-i", "sine=f=440:d=0.2",
               "-vf", filtre_v, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
               *plateforme.h264("4M"), "-c:a", "aac", "-ar", "48000", "-t", "0.2", str(sortie)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=lut.parent if lut.exists() else None,
                               encoding="utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as e:
            note(A_FAIRE, f"essai d'encodage FFmpeg impossible : {e}")
            return
        if r.returncode != 0 or not sortie.exists() or sortie.stat().st_size == 0:
            erreur = (r.stderr.strip().splitlines() or ["sans message"])[-1]
            note(A_FAIRE, f"essai d'encodage FFmpeg échoué : {erreur}",
                 "forcer l'encodeur logiciel : VIDEO_ENCODER=x264 dans .env, puis relancer le diagnostic")
            return
        p = lancer(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(sortie)])
        try:
            duree = f"{float(p.stdout.strip()):.2f}".replace(".", ",") + " s"
        except (AttributeError, ValueError):
            duree = "illisible"
        note(OK, f"essai d'encodage : 0,2 s en {plateforme.encodeur()}"
                 f"{' avec LUT' if lut.exists() else ''} et loudnorm, durée relue {duree}")


# ------------------------------------------------------------------ Node et HyperFrames
def version_node() -> tuple[int, str, str]:
    """(majeure, texte, source) du Node que le pipeline utilisera : PATH d'abord, puis nvm hors Windows."""
    node = shutil.which("node")
    if node:
        r = lancer([node, "--version"])
        v = r.stdout.strip() if r and r.returncode == 0 else ""
        m = re.match(r"v(\d+)", v)
        if m and int(m.group(1)) >= 22:
            return int(m.group(1)), v, "au PATH"
    else:
        v = ""
    nvm = Path.home() / ".nvm" / "nvm.sh"
    if not WINDOWS and nvm.exists() and shutil.which("bash"):
        r = lancer(["bash", "-lc", f'source "{nvm}" && nvm use 22 >/dev/null 2>&1 && node --version'])
        m = re.match(r"v(\d+)", r.stdout.strip() if r else "")
        if m:
            return int(m.group(1)), r.stdout.strip(), "par nvm"
    m = re.match(r"v(\d+)", v)
    return (int(m.group(1)) if m else 0), v, "au PATH"


def verifier_node() -> None:
    nvm = not WINDOWS and (Path.home() / ".nvm" / "nvm.sh").exists()
    corr = "nvm install 22" if nvm else selon(
        "brew install node",
        "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash\n"
        "source ~/.nvm/nvm.sh && nvm install 22",
        "winget install OpenJS.NodeJS.LTS")
    majeure, texte, source = version_node()
    if majeure >= 22:
        note(OK, f"Node.js {texte} ({source})")
    elif majeure:
        note(A_FAIRE, f"Node.js {texte} : il faut 22 ou plus", corr)
    else:
        note(A_FAIRE, "Node.js introuvable", corr)

    paquet = ROOT / "node_modules" / "hyperframes" / "package.json"
    if paquet.exists():
        try:
            version = json.loads(paquet.read_text(encoding="utf-8")).get("version", "?")
        except (OSError, ValueError):
            version = "?"
        note(OK, f"HyperFrames {version} (node_modules)")
    else:
        note(A_FAIRE, "HyperFrames absent de node_modules", "npm install   (à la racine du dépôt)")


def trouver_chrome() -> str | None:
    force = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    if force and Path(force).exists():
        return force
    cache = [Path.home() / ".cache" / "hyperframes" / "chrome", Path.home() / ".cache" / "puppeteer" / "chrome-headless-shell"]
    for d in cache:
        if d.is_dir() and any(d.iterdir()):
            return f"{d} (téléchargé par HyperFrames)"
    if WINDOWS:
        bases = [os.environ.get(v) for v in ("ProgramW6432", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        cands = [Path(b) / sous for b in bases if b
                 for sous in (Path("Google/Chrome/Application/chrome.exe"), Path("Chromium/Application/chrome.exe"))]
    elif MAC:
        cands = [base / app for base in (Path("/Applications"), Path.home() / "Applications")
                 for app in ("Google Chrome.app/Contents/MacOS/Google Chrome", "Chromium.app/Contents/MacOS/Chromium")]
    else:
        cands = [Path(p) for p in (shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium",
                                                            "chromium-browser")) if p]
        cands += [Path("/opt/google/chrome/chrome"), Path("/snap/bin/chromium")]
    return next((str(c) for c in cands if c.exists()), None)


def verifier_chrome() -> None:
    chrome = trouver_chrome()
    if chrome:
        note(OK, f"Chrome : {chrome}")
    else:
        note(A_FAIRE, "Google Chrome ou Chromium introuvable", selon(
            "brew install --cask google-chrome",
            "wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb\n"
            "sudo apt install -y ./google-chrome-stable_current_amd64.deb",
            "winget install Google.Chrome"))


# ------------------------------------------------------------------ outils Python du pipeline
def verifier_auto_editor() -> None:
    try:
        chemin = plateforme.outil("auto-editor")
    except SystemExit:
        note(A_FAIRE, "auto-editor introuvable", INSTALLER_DEPS)
        return
    r = lancer([chemin, "--version"])
    version = r.stdout.strip().splitlines()[0] if r and r.returncode == 0 and r.stdout.strip() else ""
    note(OK, f"auto-editor {version}".rstrip())


def verifier_whisper(rapide: bool) -> None:
    moteur = plateforme.moteur_whisper()
    module = "mlx_whisper" if moteur == "mlx" else "faster_whisper"
    if moteur == "mlx" and not MAC_ARM:
        note(A_FAIRE, "WHISPER_BACKEND=mlx demande un Mac à puce Apple", "retirer WHISPER_BACKEND de .env (ou de l'environnement), ou mettre faster")
        return
    paquet = module.replace("_", "-")
    if importlib.util.find_spec(module) is None:
        note(A_FAIRE, f"transcription {moteur} : module {module} absent",
             f"uv pip install --python {VENV_PY} {paquet}" if os.environ.get("WHISPER_BACKEND") else INSTALLER_DEPS)
        return
    if not rapide:
        try:
            importlib.import_module(module)
        except Exception as e:  # une installation cassée lève n'importe quoi à l'import
            note(A_FAIRE, f"transcription {moteur} : {module} ne se charge pas ({type(e).__name__}: {e})",
                 f"uv pip install --python {VENV_PY} --reinstall {paquet}")
            return
    note(OK, f"transcription : {module} (modèle {plateforme.WHISPER_MODEL})")

    hub = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub")
    present = hub.is_dir() and any(f"whisper-{plateforme.WHISPER_MODEL}" in d.name for d in hub.iterdir())
    if not present:
        note(FACULTATIF, f"modèle Whisper {plateforme.WHISPER_MODEL} pas encore téléchargé : il le sera au premier montage")


# ------------------------------------------------------------------ modèle de langue et clés
def cle(nom: str) -> bool:
    return bool(os.environ.get(nom, "").strip())


def remplir(nom: str) -> str:
    if (ROOT / ".env").exists():
        return f"remplir {nom}= dans .env"
    return f"{copier_cmd('.env.example', '.env')}\npuis remplir {nom}= dans .env"


def verifier_llm() -> None:
    import llm

    try:
        fournisseur, modele = llm.resolve(None, None)
    except SystemExit as e:
        note(A_FAIRE, str(e), f"LLM_PROVIDER= dans .env : {', '.join(llm.PROVIDERS)}")
        return
    if fournisseur == "claude-cli":
        if shutil.which("claude"):
            note(OK, f"modèle de langue : claude-cli ({modele}), claude présent au PATH (connexion non vérifiée)")
        else:
            note(A_FAIRE, "modèle de langue : claude-cli, mais claude introuvable au PATH",
                 "npm install -g @anthropic-ai/claude-code\nclaude login\n"
                 "ou choisir un autre fournisseur : LLM_PROVIDER= dans .env")
        return
    nom = {"anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"}[fournisseur]
    base = os.environ.get("OPENAI_BASE_URL", "")
    if fournisseur == "openai" and ("localhost" in base or "127.0.0.1" in base):
        note(OK, f"modèle de langue : openai ({modele}) par {base}, service local sans clé")
    elif cle(nom):
        note(OK, f"modèle de langue : {fournisseur} ({modele}), {nom} présente")
    else:
        note(A_FAIRE, f"modèle de langue : {fournisseur} ({modele}), {nom} absente", remplir(nom))


# fournisseurs de pipeline/generer.py : (défaut, {fournisseur: clé})
GENERATION = {"IMAGE_PROVIDER": ("openai", {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}),
              "VIDEO_GEN_PROVIDER": ("gemini", {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY"})}


def verifier_fournisseur(variable: str, usage: str) -> None:
    defaut, cles = GENERATION[variable]
    fournisseur = os.environ.get(variable, "").strip().lower() or defaut
    regle = f"{variable}={fournisseur}" if os.environ.get(variable, "").strip() else f"{variable} par défaut ({fournisseur})"
    if fournisseur not in cles:
        note(FACULTATIF, f"{variable}={fournisseur} inconnu ({usage})", f"{variable}= dans .env : {', '.join(cles)}")
        return
    nom = cles[fournisseur]
    if cle(nom):
        note(OK, f"{regle}, {nom} présente : {usage}")
    else:
        note(FACULTATIF, f"{regle}, {nom} absente ({usage})", remplir(nom))


def verifier_cles_facultatives() -> None:
    for nom, usage in (("PEXELS_API_KEY", "b-roll de banque Pexels (sans clé, seulement le b-roll du client)"),
                       ("ELEVENLABS_API_KEY", "voix off, effets sonores, musique et jingles par ElevenLabs")):
        if cle(nom):
            note(OK, f"{nom} présente : {usage}")
        else:
            note(FACULTATIF, f"{nom} absente : {usage}", remplir(nom))
    verifier_fournisseur("IMAGE_PROVIDER", "images générées par IA pour le b-roll")
    verifier_fournisseur("VIDEO_GEN_PROVIDER", "vidéos générées par IA pour le b-roll")


# ------------------------------------------------------------------ profils clients
def verifier_clients() -> None:
    profils = sorted(p.stem for p in (ROOT / "clients").glob("*.json")
                     if not p.name.startswith("_") and not p.name.startswith("exemple"))
    if profils:
        note(OK, f"profils clients : {', '.join(profils)}")
    else:
        note(A_FAIRE, "aucun profil client dans clients/ (hors gabarit et exemple)",
             f"{copier_cmd('clients/_template.json', 'clients/mon-client.json')}\npuis l'adapter (nom, couleur, noms propres, CTA)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Vérifie l'installation du pipeline de montage.")
    ap.add_argument("--rapide", action="store_true", help="sans essai d'encodage ni chargement du module Whisper")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass

    systeme = "Windows" if WINDOWS else "macOS" + (" (puce Apple)" if MAC_ARM else "") if MAC else "Linux"
    print(f"Diagnostic du pipeline, {systeme}\n")

    print("Python")
    verifier_python()
    verifier_modules()
    print("\nFFmpeg")
    if verifier_ffmpeg() and verifier_encodeur() and not args.rapide:
        essai_encodage()
    print("\nRendu HyperFrames")
    verifier_node()
    verifier_chrome()
    print("\nCoupe et transcription")
    verifier_auto_editor()
    verifier_whisper(args.rapide)
    print("\nModèle de langue")
    verifier_llm()
    print("\nClés facultatives")
    verifier_cles_facultatives()
    if not (ROOT / ".env").exists():
        note(FACULTATIF, ".env absent : les clés ne viennent que des variables d'environnement",
             copier_cmd(".env.example", ".env"))
    print("\nProfils clients")
    verifier_clients()

    a_faire = sum(1 for statut, _, _ in resultats if statut == A_FAIRE)
    print()
    if a_faire:
        print(f"{a_faire} point{'s' if a_faire > 1 else ''} obligatoire{'s' if a_faire > 1 else ''} à faire.")
        return 1
    print("Tout l'obligatoire est prêt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
