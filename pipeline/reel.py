#!/usr/bin/env python3
"""Pipeline de montage de reels verticaux (gabarit Balgio).

Étapes, chacune mise en cache dans le dossier de travail :
  1. normalize   rush -> 1080x1920, 30 i/s, H.264 (VideoToolbox)
  2. cut         coupe des silences (auto-editor)
  3. transcribe  mlx-whisper, horodatage par mot
  4. edito       modèle de langue (Claude, Gemini, OpenAI... voir llm.py) : corrections, pages, b-roll
  5. broll       b-roll local du client, sinon Pexels
  6. compose     index.html HyperFrames depuis le gabarit Balgio
  7. render      hyperframes render, loudnorm, nom de fichier AAAA-MM_Titre, planche de contact

Usage :
  .venv/bin/python pipeline/reel.py --client mon-client \
      --rush work/mon-projet/promo/src/C0001.MP4 --work work/mon-projet/promo \
      [--brief fichier.txt] [--mois 2026-05] [--jusqua render] [--llm gemini] [--model gemini-2.5-pro]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import math
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import complete_json  # noqa: E402
from plateforme import commande_hyperframes, h264, outil, transcrire, MAC_ARM  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates" / "balgio-reel"
OUT_DIR = ROOT / "out"

FS_BARRE = 132
STEPS = ["normalize", "cut", "transcribe", "edito", "broll", "compose", "render"]


# ----------------------------------------------------------------- utilitaires
def log(msg: str) -> None:
    print(f"[reel] {msg}", flush=True)


def sh(cmd: list, **kw) -> subprocess.CompletedProcess:
    log("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(sd["rotation"])
    return {
        "duration": float(data["format"].get("duration", 0)),
        "width": int(v.get("width", 0)),
        "height": int(v.get("height", 0)),
        "rotation": rot,
        "has_audio": a is not None,
    }


def slugify(text: str, max_words: int = 7) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    words = [w for w in text.split("-") if w][:max_words]
    return "-".join(w[:1].upper() + w[1:] for w in words)


def load_profile(client: str) -> dict:
    p = ROOT / "clients" / f"{client}.json"
    if not p.exists():
        sys.exit(f"Profil client introuvable : {p}")
    return json.loads(p.read_text())


# ------------------------------------------------------------------- 1. normalize
def count_faces(video: Path, vf: str, times: list[float]) -> float:
    """Score de visages à l'endroit sur quelques images, après le filtre vf (test d'orientation)."""
    import cv2
    import numpy as np

    # YuNet (réseau) plutôt que Haar ; on vérifie en plus que le visage est à l'endroit.
    det = cv2.FaceDetectorYN.create(str(ROOT / "pipeline/models/face_detection_yunet_2023mar.onnx"), "", (540, 540), 0.8)
    n = 0.0
    for t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                            "-vf", f"{vf},scale=540:-2" if vf else "scale=540:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True)
        if not r.stdout:
            continue
        img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        if faces is None:
            continue
        for f in faces:
            # YuNet voit aussi un visage à l'envers (tournage du 12 oct 2026 : égalité 6-6),
            # mais avec un score plus bas (0,86 contre 0,94). On somme les scores et on
            # favorise un visage dans la moitié haute du cadre (tête en haut).
            cy = f[1] + f[3] / 2
            n += float(f[14]) + (0.5 if cy < h / 2 else 0.0)
    return n


def face_box(video: Path, t: float):
    """Boîte du visage (x, y, w, h) en pixels 1080x1920 à l'instant t, ou None."""
    import cv2
    import numpy as np

    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=540:960", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if not r.stdout:
        return None
    img = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    det = cv2.FaceDetectorYN.create(str(ROOT / "pipeline/models/face_detection_yunet_2023mar.onnx"), "", (540, 960), 0.7)
    _, faces = det.detect(img)
    if faces is None or len(faces) == 0:
        return None
    x, y, w, h = faces[0][:4]
    return (int(x * 2), int(y * 2), int(w * 2), int(h * 2))


def rotation_scores(rush: Path) -> dict | None:
    """Visages détectés pour chaque orientation ; None si le rush n'a pas besoin de test."""
    info = probe(rush)
    if info["rotation"] or info["height"] >= info["width"]:
        return None
    times = [info["duration"] * f for f in (0.1, 0.25, 0.4, 0.55, 0.7, 0.85)]
    return {vf: count_faces(rush, vf, times) for vf in ("", "transpose=1", "transpose=2")}


def detect_rotation(rush: Path, scores: dict | None = None) -> str:
    """Un rush en paysage sans métadonnée de rotation a souvent été tourné caméra sur le côté.
    On teste les trois orientations et on garde celle où l'on voit le plus de visages."""
    if scores is None:
        scores = rotation_scores(rush)
    if not scores:
        return ""
    best = max(scores, key=scores.get)
    log(f"normalize : orientation par visages {scores} -> {best or 'aucune rotation'}")
    return best if scores[best] > 0 else ""


LUTS = {"slog3": ROOT / "pipeline" / "luts" / "slog3-sgamut3-to-rec709.cube"}


def detect_log(rush: Path) -> str:
    """Un rush en S-Log est plat : saturation moyenne très basse et hautes lumières
    qui plafonnent bien sous 255. Retourne le nom de la LUT à appliquer, ou ''."""
    info = probe(rush)
    mid = max(0.0, info["duration"] / 2 - 1.5)
    r = sh(["ffmpeg", "-v", "error", "-ss", f"{mid:.2f}", "-t", "3", "-i", rush,
            "-vf", "fps=2,signalstats,metadata=print:key=lavfi.signalstats.SATAVG:file=-,"
                   "metadata=print:key=lavfi.signalstats.YHIGH:file=-", "-f", "null", "-"],
           capture_output=True, text=True)
    txt = r.stdout + r.stderr
    sat = [float(m) for m in re.findall(r"SATAVG=([0-9.]+)", txt)]
    yhi = [float(m) for m in re.findall(r"YHIGH=([0-9.]+)", txt)]
    if not sat or not yhi:
        return ""
    s, y = sum(sat) / len(sat), sum(yhi) / len(yhi)
    # saturation seule suffit (du Rec.709 normal dépasse 25) ; le plafond des hautes lumières
    # ne sert qu'en zone grise (une fenêtre claire monte YHIGH même en S-Log : C0011, 192)
    is_log = s < 15 or (s < 20 and y < 175)
    log(f"normalize : saturation {s:.0f}, hautes lumières {y:.0f} -> {'S-Log3 détecté, LUT Rec.709' if is_log else 'image déjà Rec.709'}")
    return "slog3" if is_log else ""


def step_normalize(rush: Path, work: Path, rotation: str = "auto", lut: str = "auto") -> Path:
    out = work / "rush_1080.mp4"
    if out.exists():
        log("normalize : déjà fait")
        return out
    vf = {"auto": None, "none": "", "cw": "transpose=1", "ccw": "transpose=2"}[rotation]
    if vf is None:
        vf = detect_rotation(rush)
    if lut == "auto":
        lut = detect_log(rush)
    if lut and lut != "none":
        cube = LUTS.get(lut, Path(lut))
        vf = (vf + "," if vf else "") + f"lut3d={cube}"
    pre = (vf + ",") if vf else ""
    sh([
        "ffmpeg", "-v", "error", "-y", "-i", rush,
        "-vf", pre + "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
        *h264("12M"), "-profile:v", "high", "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out,
    ])
    return out


# ------------------------------------------------------------------------ 2. cut
def step_cut(src: Path, work: Path, margin: float = 0.3, threshold: float = 0.04) -> Path:
    """Retire seulement les vrais silences (0,5 s et plus), garde les respirations."""
    out = work / "rush_cut.mp4"
    if out.exists():
        log("cut : déjà fait")
        return out
    sh([
        outil("auto-editor"), src, "--margin", f"{margin}s",
        "--edit", f"audio:threshold={threshold},mincut=0.5s,minclip=0.3s", "-o", out, "--no-open",
    ], stdout=subprocess.DEVNULL)
    return out


# ------------------------------------------------------------------ 3. transcribe
def step_transcribe(video: Path, work: Path, profile: dict) -> Path:
    out = work / "words.json"
    if out.exists():
        log("transcribe : déjà fait")
        return out
    wav = work / "audio16k.wav"
    sh(["ffmpeg", "-v", "error", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav])
    lang = str(profile.get("langue", "fr"))[:2].lower()
    prompt = ("Vidéo québécoise. " if lang == "fr" else "Quebec business video. ") + ", ".join(profile.get("noms_propres", [])) + "."
    # condition_on_previous_text=False (dans transcrire) : sinon Whisper peut sauter 20 s de parole après un passage flou
    r = transcrire(wav, lang, prompt)
    words = []
    ELIS = {"c", "d", "j", "l", "m", "n", "s", "t", "qu", "jusqu", "lorsqu", "puisqu", "quelqu"}
    raw = [w for seg in r["segments"] for w in seg.get("words", [])]
    # seconde passe : un trou de plus de 6 s où l'enveloppe montre de la parole est retranscrit seul
    # (Whisper décroche parfois sur un passage plus bas ou flou et saute 20 s de parole)
    try:
        env, hop = load_envelope(wav)
        import numpy as np
        dur = len(env) * hop
        bounds = [0.0] + [t for w in raw for t in (float(w["start"]), float(w["end"]))] + [dur]
        holes = [(a, b) for a, b in zip(bounds[1::2][:-1] if False else bounds[0::2], bounds[1::2]) if b - a > 6.0]
        extra = []
        for a, b in holes:
            seg_env = env[int(a / hop):int(b / hop)]
            if seg_env.size and float(np.mean(seg_env > 0.02)) > 0.25:
                part = work / "_trou.wav"
                sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", wav, part])
                r2 = transcrire(part, lang, prompt)
                got = [dict(w, start=float(w["start"]) + a, end=float(w["end"]) + a) for sg in r2["segments"] for w in sg.get("words", [])]
                log(f"transcribe : trou {a:.1f}-{b:.1f} s retranscrit, {len(got)} mots")
                extra += got
        if extra:
            raw = sorted(raw + extra, key=lambda w: float(w["start"]))
    except Exception as ex:
        log(f"transcribe : seconde passe ignorée ({ex})")
    for w in raw:
        if True:
            t = w["word"].strip()
            t = re.sub(r"[.,;:!?«»\"()…]+", "", t).strip()
            # nombre coupé par Whisper (« 2 » puis « 50 » après « , ») : on recolle « 2,50 »
            if words and re.fullmatch(r"\d+", t) and re.fullmatch(r"\d+", words[-1]["text"]) and w["word"].lstrip().startswith(","):
                words[-1]["text"] += "," + t
                words[-1]["end"] = float(w["end"])
                continue
            # élision séparée par Whisper (« l » puis « 'ingénierie ») : on recolle au mot précédent
            if words and t.startswith("'") and words[-1]["text"].lower() in ELIS:
                words[-1]["text"] += t
                words[-1]["end"] = float(w["end"])
                continue
            if not t:
                continue
            if words and (t.startswith("'") or t.startswith("\u2019")):
                # mlx-whisper coupe « j'en » en « j » + « 'en » : on recolle
                words[-1]["text"] += t.replace("\u2019", "'")
                words[-1]["end"] = round(float(w["end"]), 3)
                continue
            words.append({"i": len(words), "text": t.replace("\u2019", "'"),
                          "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)})
    out.write_text(json.dumps({"text": r["text"].strip(), "words": words}, ensure_ascii=False, indent=1))
    log(f"transcribe : {len(words)} mots")
    return out


# ------------------------------------------------------------------------ 4. edito
EDITO_PROMPT = """Tu es un monteur vidéo d'expérience dans une agence de marketing.
Tu prépares les sous-titres et le b-roll d'un reel vertical (Instagram, TikTok, Facebook) pour un client.

CLIENT
{profil}

BRIEF (peut être vide)
{brief}

TRANSCRIPT (index, mot, début, fin en secondes)
{mots}

TA TÂCHE
Réponds UNIQUEMENT avec un objet JSON valide, sans texte autour, sans bloc de code, avec exactement ces clés :

LANGUE DU REEL : {langue}. L'accroche, les corrections et toute phrase écrite sont dans cette langue (si anglais : anglais nord-américain simple, pas de traduction du discours).
"titre_slug" : titre court du reel en français sans accent, 3 à 6 mots séparés par des tirets, qui décrit le sujet (ex. "Delais-de-livraison-garantis").

"corrections" : objet {{"index": "mot corrigé"}} pour chaque mot mal transcrit. Corrige l'orthographe, les noms propres du client, les anglicismes courants du Québec gardés tels quels à l'oral (contracteur, canceller restent). Retire toute ponctuation sauf les apostrophes et les traits d'union. Ne fusionne pas et ne supprime pas de mot. Garde les majuscules seulement sur les noms propres.

"pages" : liste ordonnée qui couvre TOUS les index de mots, dans l'ordre, sans trou ni chevauchement. Chaque page = {{"mots": [index...], "style": "normal" | "big" | "script" | "box"}}.
- 1 à 3 mots par page, jamais plus. Coupe aux frontières naturelles (groupe nominal, verbe + complément).
- "normal" presque partout.
- "big" : un seul mot, le plus fort de la phrase (un chiffre, un verbe d'impact), au plus une fois par 10 secondes.
- "script" : 1 ou 2 mots émotifs ou familiers, au plus une fois par 10 secondes.
- "box" : 2 ou 3 mots qui forment la promesse, le prix, la date, le lieu. Au plus 3 fois dans la vidéo.
- Jamais deux pages stylées de suite.
- Les mots de remplissage (euh, là, tsé, ben) restent dans la page de leur voisin, jamais seuls.

"accroche" : {{"texte": "titre de 6 à 10 mots qui résume l'histoire ou la promesse, en français parlé du Québec, un mot clé entre *étoiles* pour la couleur d'accent", "fin_mot": index du dernier mot pendant lequel l'accroche reste affichée (2 à 4 secondes après le début)}}. L'accroche s'affiche en haut de l'image pendant que la personne parle. Elle doit donner envie de rester : un enjeu, un chiffre, une surprise. Jamais une phrase générique.

B-ROLL DISPONIBLE CHEZ LE CLIENT (à préférer à toute image de banque)
{broll_local}

"broll" : liste de 2 à 5 fenêtres {{"debut_mot": index, "fin_mot": index, "source": "local:<id>" ou "pexels:<requête en anglais, 3 à 5 mots, concrète>", "pourquoi": "une phrase"}}.
- Chaque fenêtre dure 2 à 4 secondes de parole.
- Jamais dans les 3 premières secondes (le hook montre le visage) ni dans les 4 dernières (l'appel à l'action montre le visage).
- Au moins 4 secondes de visage entre deux fenêtres.
- Le b-roll illustre ce qui est dit à ce moment précis (un lieu, un objet, une action), pas une idée abstraite.
- Règle d'or : le produit et le magasin du client d'abord (source local). Une image de banque seulement pour une action générique que le client n'a pas filmée, et seulement si elle ne contredit pas l'histoire (pas de camion de marque différente, pas de décor étranger reconnaissable). Dans le doute, pas de b-roll : le visage avec un recadrage fait le travail.
- Pour un clip local, "debut_source" (secondes) choisit le point d'entrée dans le clip quand sa description indique plusieurs moments.
- Si rien ne mérite un b-roll, liste vide.

"impacts" : liste de 1 à 3 moments forts {{"mot": index, "type": "punch" ou "impact"}}. "punch" = recadrage sec sur le visage avec un whoosh (surprise, chiffre). "impact" = le mot s'affiche plein cadre avec un coup de basse (la chute de l'histoire, la promesse). Jamais dans un b-roll.

"extrait" : si le transcript dure plus de 75 secondes (entrevue, plusieurs sujets), choisis UN passage autonome de 30 à 60 secondes qui se tient seul, avec un début qui accroche et une fin forte : {{"debut_mot": index, "fin_mot": index, "sujet": "une ligne"}}. Sinon, omets la clé. Les coupes ci-dessous s'appliquent à l'intérieur de l'extrait.

"coupes" : liste de plages de mots à RETIRER du montage {{"debut_mot": index, "fin_mot": index, "raison": "une phrase"}}.
- Cible : 30 à 45 secondes de parole gardée (le brief peut dire autrement). Un monteur d'expérience coupe tout ce qui ne fait pas avancer l'histoire ou la promesse.
- Retire les faux départs, les reprises (la phrase recommencée, garder la meilleure version, en général la dernière), les échanges avec l'équipe de tournage (« ok, ça tourne », « je me suis coupé », « on la refait »), les hésitations longues et les digressions.
- Une idée se dit UNE fois : quand la personne répète (« je l'avais averti » trois fois, « je passe à côté » deux fois), garde la version la plus imagée ou la plus forte et coupe les autres.
- Retire les transitions creuses (« OK », « c'est bon », « donc c'est ça », « finalement il part, pas de nouvelles ») et les détails qui ne servent pas (« je finis mon travail, je pack mes choses » quand « trois heures après » suffit).
- Termine sur la phrase la plus forte (la chute, la morale ou l'appel à l'action), jamais sur un mot de remplissage.
- Garde le hook et le fil de l'histoire. Une coupe commence et finit sur une frontière de phrase ou de groupe de sens.
- Les index de "pages" et de "broll" ne doivent contenir AUCUN mot coupé. Une fenêtre de b-roll posée juste avant une coupe est bienvenue : elle cache le saut.

"cta_present" : true si le discours se termine par un appel à l'action clair, sinon false.
"note" : une phrase pour le réviseur humain (ce qui a été incertain)."""


def cut_set(edit: dict) -> set:
    cut = set()
    for c in edit.get("coupes", []):
        cut.update(range(int(c["debut_mot"]), int(c["fin_mot"]) + 1))
    return cut


def validate_edit(edit: dict, n_words: int) -> dict:
    ex = edit.get("extrait") or {}
    if ex:
        a, b = int(ex.get("debut_mot", 0)), int(ex.get("fin_mot", n_words - 1))
        coupes = edit.setdefault("coupes", [])
        have = {(int(c["debut_mot"]), int(c["fin_mot"])) for c in coupes}
        if a > 0 and (0, a - 1) not in have:
            coupes.append({"debut_mot": 0, "fin_mot": a - 1, "raison": "avant l'extrait choisi"})
        if b < n_words - 1 and (b + 1, n_words - 1) not in have:
            coupes.append({"debut_mot": b + 1, "fin_mot": n_words - 1, "raison": "après l'extrait choisi"})
    cut = cut_set(edit)
    kept = [i for i in range(n_words) if i not in cut]
    pages = []
    for p in edit["pages"]:
        mots = [i for i in p["mots"] if i not in cut]
        if not mots:
            continue
        if len(mots) > 3:
            raise ValueError(f"page hors norme : {p}")
        pages.append({"mots": mots, "style": p.get("style", "normal"), **({"x_mot": int(p["x_mot"])} if "x_mot" in p else {})})
    seen = [i for p in pages for i in p["mots"]]
    missing = [i for i in kept if i not in seen]
    if missing:
        log(f"edito : {len(missing)} mots non couverts, pages ajoutées")
        pages.extend({"mots": [i], "style": "normal"} for i in missing)
    pages.sort(key=lambda p: p["mots"][0])
    edit["pages"] = pages
    edit["broll"] = [b for b in edit.get("broll", [])
                     if b["debut_mot"] not in cut and b["fin_mot"] not in cut]
    return edit


def step_edito(words_json: Path, work: Path, profile: dict, brief: str, model: str | None, llm: str | None = None) -> Path:
    out = work / "edit.json"
    if out.exists():
        log("edito : déjà fait")
        return out
    words = json.loads(words_json.read_text())["words"]
    mots = "\n".join(f'{w["i"]}\t{w["text"]}\t{w["start"]:.2f}\t{w["end"]:.2f}' for w in words)
    profil = json.dumps({k: profile[k] for k in profile if k not in ("broll", "carte_fin")},
                        ensure_ascii=False, indent=1)
    index = load_broll_index(work)
    broll_local = "\n".join(f'- local:{b["id"]} ({b["type"]}{", " + str(b["duree"]) + " s" if b.get("duree") else ""}) : {b["description"]}'
                            for b in index) or "(aucun)"
    langue = "anglais" if str(profile.get("langue", "fr")).lower().startswith("en") else "français du Québec"
    prompt = EDITO_PROMPT.format(profil=profil, brief=brief or "(aucun)", mots=mots, broll_local=broll_local, langue=langue)
    edit = validate_edit(complete_json(prompt, llm, model, log), len(words))
    out.write_text(json.dumps(edit, ensure_ascii=False, indent=1))
    log(f"edito : {len(edit['pages'])} pages, {len(edit.get('broll', []))} fenêtres de b-roll, "
        f"{len(edit.get('corrections', {}))} corrections")
    return out


# ------------------------------------------------------------------------ 5. broll
def pexels_search(query: str, api_key: str, per_page: int = 8) -> list:
    import requests

    r = requests.get(
        "https://api.pexels.com/videos/search",
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": per_page},
        headers={"Authorization": api_key}, timeout=30,
    )
    r.raise_for_status()
    return r.json().get("videos", [])


def pick_file(video: dict) -> dict | None:
    files = [f for f in video.get("video_files", []) if f.get("height", 0) > f.get("width", 0)]
    files = [f for f in files if f.get("width", 0) >= 1080]
    if not files:
        return None
    return sorted(files, key=lambda f: f["width"])[0]  # le plus petit >= 1080


def load_broll_index(work: Path) -> list[dict]:
    """B-roll fourni par le client : work/<client>/assets/broll/index.json (fichiers à côté)."""
    p = work.parent / "assets" / "broll" / "index.json"
    if not p.exists():
        return []
    items = json.loads(p.read_text())
    for b in items:
        b["path"] = str(p.parent / b["file"])
    # photos de produits du site du client (assets/produits/index.json) : un plancher nommé
    # se montre avec sa vraie photo, jamais avec un plancher générique
    q = work.parent / "assets" / "produits" / "index.json"
    if q.exists():
        for x in json.loads(q.read_text()):
            if x.get("fichiers"):
                items.append({"id": x["id"], "file": x["fichiers"][0], "type": "photo", "description": x["nom"],
                              "tags": x.get("tags", []), "path": str(q.parent / x["fichiers"][0])})
    return items


def step_broll(edit_json: Path, words_json: Path, work: Path, profile: dict) -> Path:
    out = work / "broll.json"
    if out.exists():
        log("broll : déjà fait")
        return out
    words = json.loads(words_json.read_text())["words"]
    edit = validate_edit(json.loads(edit_json.read_text()), len(words))
    bdir = work / "broll"
    bdir.mkdir(exist_ok=True)
    api_key = os.environ.get("PEXELS_API_KEY", "")
    used_ids: set = set()
    result = []
    index = {b["id"]: b for b in load_broll_index(work)}
    wins = sorted(edit.get("broll", []), key=lambda x: words[x["debut_mot"]]["start"])
    spans = [(words[x["debut_mot"]]["start"], words[x["fin_mot"]]["end"]) for x in wins]
    # « duree » dans la fenêtre fixe la durée (sinon 2,2 à 4,5 s selon les mots couverts)
    durs = [float(x["duree"]) if x.get("duree") else min(max(2.2, e - s + 0.3), 4.5) for x, (s, e) in zip(wins, spans)]
    # deux fenêtres ne se chevauchent jamais : la première s'arrête 0,1 s avant la suivante
    # (plancher 0,7 s, un battement rapide quand les mots sont courts : « en vacances », « en camping »)
    for i in range(len(wins) - 1):
        limit = spans[i + 1][0] - 0.1 - spans[i][0]
        if durs[i] > limit:
            durs[i] = max(0.7, limit)
            log(f"broll {i + 1} : raccourci à {durs[i]:.1f}s pour ne pas chevaucher la fenêtre suivante")
        # jamais une demi-seconde de visage entre deux b-roll : sous 1,5 s d'écart, on enchaîne
        gap = spans[i + 1][0] - (spans[i][0] + durs[i])
        if 0 < gap < 1.5:
            manque = 1.5 - gap
            if durs[i] - manque >= 1.2 and not wins[i].get("duree"):
                durs[i] -= manque
                log(f"broll {i + 1} : raccourci à {durs[i]:.1f}s pour laisser 1,5 s de visage avant la fenêtre suivante")
            else:
                durs[i] = spans[i + 1][0] - spans[i][0]
                log(f"broll {i + 1} : étiré à {durs[i]:.1f}s, enchaîné avec la fenêtre suivante (écart de {gap:.1f}s)")
    for n, win in enumerate(wins, 1):
        start = spans[n - 1][0]
        dur = durs[n - 1]
        source = win.get("source") or ("pexels:" + win.get("requete_en", ""))
        kind, _, query = source.partition(":")
        src = None
        origin = None
        if kind == "local" and query in index:
            b = index[query]
            src, origin = Path(b["path"]), f"local:{query}"
            if b["type"] == "photo":
                result.append({"n": n, "start": round(start, 3), "duration": round(dur, 3),
                               "file": b["file"], "path": b["path"], "type": "photo", "origin": origin, "query": query,
                               "pourquoi": win.get("pourquoi", "")})
                log(f"broll {n} : photo {origin} ({start:.1f}s, {dur:.1f}s)")
                continue
        elif kind == "local":
            log(f"broll {n} : id local inconnu « {query} », fenêtre ignorée")
            continue
        if src is None and profile.get("broll", {}).get("pexels_permis") and api_key:
            if kind == "pexels-id":
                import requests

                vids = [requests.get(f"https://api.pexels.com/videos/videos/{query}",
                                     headers={"Authorization": api_key}, timeout=30).json()]
                if vids and "id" not in vids[0]:
                    log(f"broll {n} : pexels-id {query} introuvable ({vids[0]}), fenêtre ignorée")
                    vids = []
            else:
                vids = pexels_search(query, api_key)
            for v in vids:
                if v["id"] in used_ids or v.get("duration", 0) < dur:
                    continue
                f = pick_file(v)
                if not f:
                    continue
                raw = bdir / f"pexels_{v['id']}.mp4"
                if not raw.exists():
                    import requests

                    with requests.get(f["link"], stream=True, timeout=120) as r:
                        r.raise_for_status()
                        with open(raw, "wb") as fh:
                            for chunk in r.iter_content(1 << 20):
                                fh.write(chunk)
                used_ids.add(v["id"])
                src, origin = raw, f"pexels:{v['id']} ({v['user']['name']})"
                break
        if src is None:
            log(f"broll {n} : rien trouvé pour « {query} », fenêtre ignorée")
            continue
        offset = float(win.get("debut_source", 0))  # point d'entrée dans le clip source, en secondes
        # le nom porte la source et le point d'entrée : une fenêtre changée n'hérite jamais d'un ancien clip
        sid = re.sub(r"[^0-9A-Za-z]+", "-", origin.split(" ")[0].split(":", 1)[-1]).strip("-")
        clip = bdir / f"broll_{n:02d}_{sid}_{int(offset * 10)}.mp4"
        has_audio = origin.startswith("local:") and probe(src)["has_audio"]
        if not clip.exists():
            sh([
                "ffmpeg", "-v", "error", "-y", "-ss", f"{offset:.2f}", "-t", f"{dur + 0.5:.2f}", "-i", src,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
                *(["-c:a", "aac", "-b:a", "128k", "-ar", "48000"] if has_audio else ["-an"]),
                *h264("10M"), "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", clip,
            ])
        result.append({"n": n, "start": round(start, 3), "duration": round(dur, 3),
                       "file": clip.name, "type": "video", "origin": origin, "query": query,
                       "audio": bool(has_audio), "pourquoi": win.get("pourquoi", "")})
        log(f"broll {n} : {origin} pour « {query} » ({start:.1f}s, {dur:.1f}s)")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    broll_preview(result, bdir, work)
    return out


def broll_preview(result: list, bdir: Path, work: Path) -> None:
    """Bande de contrôle : trois images par fenêtre de b-roll, pour vérifier à l'œil ce qui sera montré."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return
    tiles = []
    for b in result:
        src = (bdir / b["file"]) if b.get("type", "video") == "video" else (work.parent / "assets" / "broll" / b["file"])
        for k in range(3):
            t = 0.0 if b.get("type") == "photo" else b["duration"] * (0.1 + 0.4 * k)
            r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                                "-vf", "scale=180:320", "-f", "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True)
            if r.stdout:
                import io
                tiles.append((f'{b["n"]} {b["origin"][:18]} @{b["start"]:.1f}s', Image.open(io.BytesIO(r.stdout)).convert("RGB")))
    if not tiles:
        return
    sheet = Image.new("RGB", (180 * min(len(tiles), 9), 334 * ((len(tiles) + 8) // 9)), "black")
    dr = ImageDraw.Draw(sheet)
    for i, (label, im) in enumerate(tiles):
        x, y = (i % 9) * 180, (i // 9) * 334
        sheet.paste(im, (x, y + 14)); dr.text((x + 2, y + 1), label, fill="white")
    sheet.save(bdir / "apercu.jpg", quality=85)
    log(f"broll : aperçu des fenêtres -> {bdir / 'apercu.jpg'}")


# ---------------------------------------------------------------------- 6. compose
SFX_DIR = ROOT / "node_modules/hyperframes/dist/skills/media-use/audio/assets/sfx"
SFX_VOL = {"whoosh-short": 0.30, "whoosh": 0.28, "pop": 0.22, "impact-bass-1": 0.30, "click-soft": 0.18, "ping": 0.35, "chime": 0.35}


def load_envelope(wav: Path, hop: float = 0.01):
    """Enveloppe RMS (fenêtres de 10 ms) du wav 16 kHz mono, pour placer les coupes dans les creux."""
    import wave
    import numpy as np

    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    n = int(sr * hop)
    m = len(x) // n
    env = np.sqrt((x[: m * n].reshape(m, n) ** 2).mean(axis=1) + 1e-9)
    return env, hop


def quietest(env, hop: float, lo: float, hi: float, win: float = 0.04) -> float:
    """Centre de la fenêtre de `win` s la plus silencieuse entre lo et hi."""
    import numpy as np

    i0, i1 = max(0, int(lo / hop)), min(len(env), int(hi / hop))
    k = max(1, int(win / hop))
    if i1 - i0 <= k:
        return (lo + hi) / 2
    seg = env[i0:i1]
    sums = np.convolve(seg, np.ones(k), mode="valid")
    j = int(sums.argmin())
    return (i0 + j + k / 2) * hop


def onset(env, hop: float, w_start: float, w_end: float) -> float:
    """Attaque de la voix : dernier instant avant le mot où l'enveloppe est sous 20 % du pic
    du mot (on remonte depuis le début du mot, au plus 0,45 s), moins 30 ms. Coupe la
    respiration et l'amorce, garde la consonne d'attaque."""
    import numpy as np
    i0, i1 = int(w_start / hop), min(len(env), int(w_end / hop) + 1)
    if i1 <= i0:
        return max(0.0, w_start - 0.03)
    peak = float(np.max(env[i0:i1])) if i1 > i0 else 0.0
    seuil = max(peak * 0.08, 0.004)  # 8 % du pic : un premier mot dit tout bas (« Fait que ») doit rester
    i = min(len(env) - 1, int((w_start + 0.02) / hop))
    lo = max(0, int((w_start - 0.45) / hop))
    while i > lo and env[i] >= seuil:
        i -= 1
    return max(0.0, min(i * hop - 0.03, w_start + 0.02))


def offset(env, hop: float, w_start: float, w_end: float) -> float:
    """Fin sèche : premier instant après le mot où l'enveloppe reste sous 20 % du pic du mot
    pendant 60 ms (au plus 0,35 s après), plus 120 ms d'air."""
    import numpy as np
    i0, i1 = int(w_start / hop), min(len(env), int(w_end / hop) + 1)
    peak = float(np.max(env[i0:i1])) if i1 > i0 else 0.0
    seuil = max(peak * 0.2, 0.004)
    i = max(0, int((w_end - 0.08) / hop))
    hi = min(len(env) - 6, int((w_end + 0.35) / hop))
    while i < hi and not all(env[i + k] < seuil for k in range(6)):
        i += 1
    return min(i * hop + 0.12, w_end + 0.35)


def kept_segments(edit: dict, words: list, total: float, pad: float = 0.08,
                  env=None, hop: float = 0.01) -> list[tuple[float, float]]:
    """Plages de la source conservées, après retrait des coupes (en secondes source).
    Avec une enveloppe audio, chaque frontière est posée dans le creux le plus silencieux
    entre le dernier mot gardé et le premier mot coupé (et inversement à la reprise)."""
    removed = []
    for c in edit.get("coupes", []):
        a, b = int(c["debut_mot"]), int(c["fin_mot"])
        if "debut_s" in c and "fin_s" in c:
            removed.append((max(0.0, float(c["debut_s"])), min(total, float(c["fin_s"]))))
            continue
        if a == 0:
            s = 0.0
        elif env is not None:
            # sortie sèche : 120 ms d'air après la fin de la voix du dernier mot gardé
            s = min(offset(env, hop, words[a - 1]["start"], words[a - 1]["end"]), words[a]["start"])
        else:
            s = words[a]["start"] - pad
        if b >= len(words) - 1:
            e = total
        elif env is not None:
            # reprise à l'attaque de la voix du premier mot gardé (coupe la respiration)
            e = max(onset(env, hop, words[b + 1]["start"], words[b + 1]["end"]), words[b]["end"])
        else:
            e = words[b]["end"] + pad
        removed.append((max(0.0, s), min(total, e)))
    removed.sort()
    segs, cur = [], 0.0
    for s, e in removed:
        if s > cur + 0.2:
            segs.append((cur, s))
        cur = max(cur, e)
    if total > cur + 0.2:
        segs.append((cur, total))
    # début serré sur le premier mot gardé (coupe la respiration), fin sèche après le dernier
    cut = cut_set(edit)
    kept = [i for i in range(len(words)) if i not in cut]
    if segs and kept:
        w0, w1 = words[kept[0]], words[kept[-1]]
        if env is not None:
            s0 = onset(env, hop, w0["start"], w0["end"])
            e1 = offset(env, hop, w1["start"], w1["end"])
        else:
            s0, e1 = w0["start"] - pad, w1["end"] + pad
        a, b = segs[0]
        segs[0] = (min(max(a, s0), b - 0.2), b)
        a, b = segs[-1]
        segs[-1] = (a, max(min(b, max(e1, w1["end"] + 0.05)), a + 0.2))
    return segs


def time_map(segs: list[tuple[float, float]]):
    """Renvoie une fonction source -> ligne de temps du montage."""
    def f(t: float) -> float:
        out = 0.0
        for s, e in segs:
            if t <= s:
                return out
            if t <= e:
                return out + (t - s)
            out += e - s
        return out
    return f


def mean_luma(video: Path, start: float = 1.0, dur: float = 20.0) -> float:
    """Luminance moyenne (0-255) sur une plage, via signalstats."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{start}", "-t", f"{dur}", "-i", str(video),
                        "-vf", "fps=2,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
                       capture_output=True, text=True)
    vals = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", r.stdout + r.stderr)]
    return sum(vals) / len(vals) if vals else 118.0


def grade_filter(video: Path, target: float = 118.0, sat: float = 1.08, contrast: float = 1.05, avant: str = "") -> str:
    """Correction d'exposition automatique : ramène la luminance moyenne vers la cible
    (les reels livrés par les monteurs se situent autour de 110-125), en gamma pour protéger
    les hautes lumières, avec un peu de contraste et de saturation. Vide si déjà correct."""
    import math

    y = mean_luma(video)
    if abs(y - target) < 8:
        log(f"grade : luminance {y:.0f}, rien à corriger")
        return ""
    extra = ",curves=master='0/0 0.8/0.76 1/0.97'" if y > target else ""

    def filt(g: float) -> str:
        return (avant + "," if avant else "") + f"eq=gamma={g:.3f}:contrast={contrast:.2f}:saturation={sat:.2f}{extra}"

    def measure(g: float) -> float:
        # essai sur 3 s au milieu, encodage rapide, mesure réelle (la formule seule sous-estime l'effet)
        tmp = video.parent / "_grade_test.mp4"
        mid = max(0.0, probe(video)["duration"] / 2 - 1.5)
        sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.2f}", "-t", "3", "-i", video, "-vf", filt(g),
            *h264("4M"), "-an", tmp], stdout=subprocess.DEVNULL)
        return mean_luma(tmp, 0, 3)

    e = math.log(target / 255) / math.log(max(y, 1) / 255)
    g1 = max(0.5, min(1.6, 1 / e))
    y1 = measure(g1)
    # sécante entre (1.0, y) et (g1, y1) pour viser la cible, puis bornes
    g2 = g1 if abs(y1 - y) < 1 else 1.0 + (g1 - 1.0) * (target - y) / (y1 - y)
    gamma = max(0.5, min(1.6, g2))
    log(f"grade : luminance {y:.0f} -> cible {target:.0f} ; gamma {g1:.2f} donne {y1:.0f}, retenu {gamma:.2f}")
    return filt(gamma)


def assemble_talk(src: Path, segs: list[tuple[float, float]], out: Path, vf_grade: str = "", afx: list | None = None) -> float:
    """Concatène les segments gardés en un seul fichier. L'image coupe net ; le son enchaîne
    avec un fondu croisé de 60 ms (la queue du segment sortant déborde de 60 ms dans la
    coupe, ce qui garde la fin du mot et le fond de salle continu)."""
    # cache lié aux bornes réelles : un changement de découpage refait le bloc
    key = out.with_suffix(".segs.json")
    afx = afx or []
    sig = json.dumps([[round(a, 3), round(b, 3)] for a, b in segs]) + vf_grade + json.dumps(afx)
    if out.exists() and key.exists() and key.read_text() == sig:
        return probe(out)["duration"]
    key.write_text(sig)
    xf = 0.12  # fondu croisé audio aux coupes (60 ms était trop sec quand l'ambiance change)
    parts = []
    g = ("," + vf_grade) if vf_grade else ""
    for k, (a, b) in enumerate(segs):
        img = next((x[3] for x in afx if len(x) > 3 and x[3] and x[0] - 0.05 <= (a + b) / 2 <= x[1] + 0.05), None)
        if img:
            # image prise ailleurs dans le rush (ex. la personne qui écoute pendant une voix hors champ), étirée à la durée du son
            i0, i1 = img
            parts.append(f"[0:v]trim=start={i0:.3f}:end={i1:.3f},setpts=(PTS-STARTPTS)*{(b - a) / (i1 - i0):.4f}{g}[v{k}];")
        else:
            parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS{g}[v{k}];")
        tail = xf if k < len(segs) - 1 else 0.0
        fx = next((x[2] for x in afx if x[0] - 0.05 <= (a + b) / 2 <= x[1] + 0.05), "")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b + tail:.3f},asetpts=PTS-STARTPTS{(',' + fx) if fx else ''}[a{k}];")
    vmaps = "".join(f"[v{k}]" for k in range(len(segs)))
    fc = "".join(parts) + vmaps + f"concat=n={len(segs)}:v=1:a=0[v];"
    if len(segs) == 1:
        fc += "[a0]acopy[a]"
    else:
        prev = "[a0]"
        for k in range(1, len(segs)):
            outn = "[a]" if k == len(segs) - 1 else f"[x{k}]"
            fc += f"{prev}[a{k}]acrossfade=d={xf}:c1=tri:c2=tri{outn};"
            prev = outn
        fc = fc.rstrip(";")
    sh(["ffmpeg", "-v", "error", "-y", "-i", src, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-r", "30", *h264("12M"), "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out])
    return probe(out)["duration"]


def join_tokens(toks: list[str]) -> str:
    """Joint les mots d'un sous-titre : un morceau qui commence par « - » ou « ' » se colle au
    précédent (« sous » + « -sol » -> « sous-sol », « l » + « 'eau » -> « l'eau »)."""
    out = ""
    for t in toks:
        out += t if (out and (t[:1] in "-'’" or out[-1:] in "'’")) else ((" " if out else "") + t)
    return out


def build_pages(edit: dict, words: list) -> list[dict]:
    corr = {int(k): v for k, v in edit.get("corrections", {}).items()}
    pages = []
    for p in edit["pages"]:
        idx = p["mots"]
        text = join_tokens([t for t in (corr.get(i, words[i]["text"]) for i in idx) if t])
        if not text.strip():
            continue
        pages.append({"text": text, "style": p.get("style", "normal"), "mots": idx, "x_mot": p.get("x_mot"),
                      "start": words[idx[0]]["start"], "end": words[idx[-1]]["end"]})
    # une page reste affichée jusqu'à la suivante (sans trou), au plus 0,7 s de prolongation
    for a, b in zip(pages, pages[1:]):
        a["end"] = min(b["start"], a["end"] + 0.7)
        a["end"] = max(a["end"], a["start"] + 0.3)
    if pages:
        pages[-1]["end"] = max(pages[-1]["end"], pages[-1]["start"] + 0.3) + 0.4
    return pages


def title_metrics(text: str, size: int, spacing: float = -0.03, max_w: int = 960, lh: float = 0.98):
    """Lignes, largeur et hauteur (px) d'un titre Montserrat 900 en capitales, replié comme Chrome le fera."""
    from PIL import ImageFont
    font = ImageFont.truetype(str(TEMPLATE_DIR / "fonts" / "Montserrat.ttf"), size)
    font.set_variation_by_axes([900])

    def width(t: str) -> float:
        return font.getlength(t) + spacing * size * max(0, len(t) - 1)

    lines, cur = [], ""
    for w in text.upper().split():
        cand = (cur + " " + w).strip()
        if cur and width(cand) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines, max(width(l) for l in lines), len(lines) * lh * size


def html_escape(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def balance_lines(text: str, size: int, max_w: int = 960, spacing: float = -0.02) -> list[str]:
    """Coupe un titre en lignes équilibrées (largeur mesurée dans Montserrat 900, capitales) :
    le nombre de lignes du repli glouton, puis la répartition qui minimise la ligne la plus
    longue, sans jamais laisser un mot seul sur une ligne quand on peut l'éviter."""
    from itertools import combinations
    from PIL import ImageFont
    font = ImageFont.truetype(str(TEMPLATE_DIR / "fonts" / "Montserrat.ttf"), size)
    font.set_variation_by_axes([900])
    words = []
    for w in text.split():
        if w in ("?", "!", ":", ";", "»") and words:
            words[-1] += "\u00a0" + w  # ponctuation haute collée au mot précédent (espace insécable)
        else:
            words.append(w)

    def width(ws):
        t = " ".join(w.replace("*", "") for w in ws).upper()
        return font.getlength(t) + spacing * size * max(0, len(t) - 1)

    lines, cur = [], []
    for w in words:
        if cur and width(cur + [w]) > max_w:
            lines.append(cur); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    n = len(lines)
    if n == 1 or len(words) > 14:
        return [" ".join(l) for l in lines]
    best, best_key = lines, None
    for cuts in combinations(range(1, len(words)), n - 1):
        parts = [words[a:b] for a, b in zip((0,) + cuts, cuts + (len(words),))]
        if any(width(pt) > max_w for pt in parts):
            continue
        orphan = sum(1 for pt in parts if len(pt) == 1)
        key = (orphan, max(width(pt) for pt in parts))
        if best_key is None or key < best_key:
            best, best_key = parts, key
    return [" ".join(l) for l in best]


def hook_html(text: str, size: int = 0) -> str:
    """*mot* -> accent ; avec size, lignes équilibrées (jamais un mot orphelin)."""
    if size:
        lines = balance_lines(text, size)
        fixed, carry = [], False
        for l in lines:
            if carry:
                l = "*" + l
            carry = l.count("*") % 2 == 1
            fixed.append(l + ("*" if carry else ""))
        return "<br>".join(hook_html(l) for l in fixed)
    parts = re.split(r"\*(.+?)\*", text)
    out = []
    for i, part in enumerate(parts):
        part = html_escape(part)
        out.append(f"<em>{part}</em>" if i % 2 else part)
    return "".join(out)


def step_compose(work: Path, profile: dict, edit_json: Path, words_json: Path, broll_json: Path,
                 cut: Path, endcard: Path | None, title: str) -> Path:
    comp = work / "comp"
    comp.mkdir(exist_ok=True)
    (comp / "fonts").mkdir(exist_ok=True)
    (comp / "sfx").mkdir(exist_ok=True)
    for f in (TEMPLATE_DIR / "fonts").glob("*.ttf"):
        shutil.copy2(f, comp / "fonts" / f.name)

    def link(src: Path, name: str) -> str:
        dst = comp / name
        if dst.exists():
            dst.unlink()
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
        return name

    words = json.loads(words_json.read_text())["words"]
    edit = validate_edit(json.loads(edit_json.read_text()), len(words))  # extrait -> coupes, pages complètes
    brolls = json.loads(broll_json.read_text()) if broll_json.exists() else []
    src_dur = probe(cut)["duration"]
    wav = work / "audio16k.wav"
    env, hop = load_envelope(wav) if wav.exists() else (None, 0.01)
    segs = kept_segments(edit, words, src_dur, env=env, hop=hop)
    tmap = time_map(segs)
    talk = work / "talk.mp4"
    if talk.exists() and talk.stat().st_mtime < edit_json.stat().st_mtime:
        talk.unlink()
    # étalonnage par reel : edit.json "grade": {"cible": 105, "saturation": 0.9, "contraste": 1.0}
    gr = edit.get("grade") or {}
    if "gamma" in gr:
        # gamma fixé à la main : pas de calibration automatique de luminance
        vf_grade = (str(gr.get("filtre", "")) + "," if gr.get("filtre") else "") + \
            f'eq=gamma={float(gr["gamma"]):.3f}:contrast={float(gr.get("contraste", 1.05)):.2f}:saturation={float(gr.get("saturation", 1.08)):.2f}'
        log(f"grade : réglage manuel {vf_grade}")
    else:
        # défauts plus sobres : 1,08 de saturation et une cible de 118 donnaient une image trop saturée
        vf_grade = grade_filter(cut, float(gr.get("cible", 112.0)), float(gr.get("saturation", 0.85)), float(gr.get("contraste", 1.0)), str(gr.get("filtre", "")))
    (work / "grade.txt").write_text(vf_grade)
    vf_talk = (vf_grade + "," if vf_grade else "") + "vignette=a=0.45"
    EFFETS = {"telephone": "highpass=f=420,lowpass=f=3200,acompressor=threshold=-22dB:ratio=5:attack=5:release=60,acrusher=bits=10:mix=0.12,volume=2.2"}
    voix_off = edit.get("voix_off", [])
    afx = [(words[v["debut_mot"]]["start"] - 0.08, words[v["fin_mot"]]["end"] + 0.12, EFFETS.get(v.get("effet", "telephone"), ""), v.get("image_de")) for v in voix_off]
    # une voix hors champ forme son propre segment : on coupe le segment qui la contient à ses bornes
    if afx:
        cutpts = sorted({t for x in afx for t in (x[0], x[1])})
        split = []
        for a, b in segs:
            pts = [a] + [t for t in cutpts if a + 0.05 < t < b - 0.05] + [b]
            split += list(zip(pts[:-1], pts[1:]))
        segs = split
        tmap = time_map(segs)
    pre = edit.get("preroll")
    pre_pages = []
    if pre:
        # pré-ouverture : un son fourni (ex. la question du caméraman passée en effet téléphone) posé sur un
        # passage du rush (image_de), étiré à la durée du son ; le reel enchaîne ensuite
        body = work / "talk_body.mp4"
        assemble_talk(cut, segs, body, vf_talk, afx)
        aud = Path(pre["audio"]) if Path(pre["audio"]).is_absolute() else ROOT / pre["audio"]
        D = min(probe(aud)["duration"], float(pre.get("duree", 1e9)))
        if pre.get("image_de") == "avant":
            # image continue : les D secondes du rush qui précèdent directement la reprise, à vitesse normale
            i1 = segs[0][0]
            i0 = max(0.0, i1 - D)
        else:
            i0, i1 = pre["image_de"]
        prev = work / "preroll.mp4"
        sh(["ffmpeg", "-v", "error", "-y", "-i", cut, "-i", aud, "-filter_complex",
            f"[0:v]trim=start={i0:.3f}:end={i1:.3f},setpts=(PTS-STARTPTS)*{D / (i1 - i0):.4f},{vf_talk}[v];"
            f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(pre.get('gain', 1.0)):.2f},atrim=end={D:.3f},afade=t=out:st={max(0.0, D - 0.12):.3f}:d=0.12[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{D:.3f}", "-r", "30", *h264("12M"), "-pix_fmt", "yuv420p",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", prev])
        lst = work / "_talk_parts.txt"
        lst.write_text(f"file '{prev}'\nfile '{body}'\n")
        sh(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", talk])
        talk_dur = probe(talk)["duration"]
        # sous-titres de la pré-ouverture : transcription du son fourni (mise en cache)
        pw = work / "preroll_words.json"
        if not pw.exists() or pw.stat().st_mtime < aud.stat().st_mtime:
            wav = work / "_preroll16k.wav"
            sh(["ffmpeg", "-v", "error", "-y", "-i", aud, "-vn", "-ac", "1", "-ar", "16000", wav])
            r = transcrire(wav, str(profile.get("langue", "fr"))[:2])
            pw.write_text(json.dumps([{"text": w["word"].strip(), "start": w["start"], "end": w["end"]}
                                      for sg in r["segments"] for w in sg.get("words", [])], ensure_ascii=False))
        pws = json.loads(pw.read_text())
        for k, v in (pre.get("corrections") or {}).items():
            if int(k) < len(pws):
                pws[int(k)]["text"] = v
        pws = [w for w in pws if w["text"]] if pre.get("sous_titres", True) else []
        for k in range(0, len(pws), 3):
            grp = pws[k:k + 3]
            nxt = pws[k + 3]["start"] if k + 3 < len(pws) else D
            pre_pages.append({"text": join_tokens([g["text"] for g in grp]), "style": pre.get("style", "tel"), "mots": [], "nom": pre.get("nom", ""),
                              "start": grp[0]["start"], "end": max(min(nxt, grp[-1]["end"] + 0.7), grp[0]["start"] + 0.3)})
        _tm = tmap
        tmap = lambda t, _tm=_tm, D=D: _tm(t) + D
    else:
        talk_dur = assemble_talk(cut, segs, talk, vf_talk, afx)
    vo_words = {i for v in voix_off for i in range(v["debut_mot"], v["fin_mot"] + 1)}
    vo_nom = {i: v.get("nom", "") for v in voix_off for i in range(v["debut_mot"], v["fin_mot"] + 1)}
    talk_name = link(talk, "talk.mp4")

    pages = build_pages(edit, words)
    for p in pages:
        p["start"], p["end"] = tmap(p["start"]), tmap(p["end"])
    pages = [p for p in pages if p["end"] - p["start"] > 0.05]
    pages = pre_pages + pages
    for b in brolls:
        b["start"] = tmap(b["start"])
    impacts = {int(i["mot"]): i["type"] for i in edit.get("impacts", [])}

    tweens, sfx = [], []

    def cue(name: str, t: float) -> None:
        if (SFX_DIR / f"{name}.mp3").exists() and t >= 0:
            sfx.append((name, t))

    # --- mouvement de la tête parlante : une seule piste d'échelle, sans chevauchement.
    # Événements : coupe (recadrage alterné), punch, impact, retour de b-roll. Entre deux
    # événements, une poussée lente continue (jamais d'image fixe).
    events = []
    t = 0.0
    for k, (a, b) in enumerate(segs):
        events.append((t, "cut", 1.0 if k % 2 == 0 else 1.06))
        t += b - a
    for mot, kind in impacts.items():
        if mot < len(words):
            at = tmap(words[mot]["start"])
            events.append((at, kind, None))
            cue("whoosh-short" if kind == "punch" else "whoosh", at - (0.08 if kind == "punch" else 0.06))
    events.sort(key=lambda e: e[0])
    # micro-recadrages aux débuts de phrase (pause > 0,25 s avant), si rien n'a bougé depuis 5 s
    busy = sorted([e[0] for e in events] + [b["start"] for b in brolls] + [b["start"] + b["duration"] for b in brolls])
    for a, b in zip(pages, pages[1:]):
        if b["start"] - a["end"] >= 0.25 and all(abs(b["start"] - x) > 5.0 for x in busy):
            events.append((b["start"], "micro", None)); busy.append(b["start"])
    events.sort(key=lambda e: e[0])
    bounds = [e[0] for e in events[1:]] + [talk_dur]
    for (at, kind, base), nxt in zip(events, bounds):
        span = nxt - at
        if span <= 0.05:
            continue
        snap = {"punch": (1.16, 1.08, 0.5, "power2.out"), "impact": (1.12, 1.05, 0.7, "power3.out"),
                "micro": (1.06, 1.01, 0.45, "power2.out")}.get(kind)
        if snap:
            s0, s1, d, ease = snap
            d = min(d, span)
            tweens.append(f'      tl.fromTo("#talk", {{scale: {s0}}}, {{scale: {s1}, duration: {d:.3f}, ease: "{ease}"}}, {at:.3f});')
            if span - d > 0.1:
                tweens.append(f'      tl.fromTo("#talk", {{scale: {s1}}}, {{scale: {s1 + 0.04:.3f}, duration: {span - d:.3f}, ease: "none"}}, {at + d:.3f});')
        else:
            tweens.append(f'      tl.fromTo("#talk", {{scale: {base:.3f}}}, {{scale: {base + 0.05:.3f}, duration: {span:.3f}, ease: "none"}}, {at:.3f});')

    # --- sous-titres (mot courant en couleur d'accent sur les pages normales)
    corr = {int(k): v for k, v in edit.get("corrections", {}).items()}
    accent = profile.get("couleur_marque", "#E8843C")
    caps = []
    for k, p in enumerate(pages):
        dur = p["end"] - p["start"]
        style = p["style"]
        if any(m in impacts and impacts[m] == "impact" for m in p["mots"]):
            style = "impact"
        if p["mots"] and all(m in vo_words for m in p["mots"]):
            style = "tel"
        if style == "normal" and p["mots"]:
            spans = []
            prev_txt = ""
            for j, m in enumerate(p["mots"]):
                txt = corr.get(m, words[m]["text"])
                if not txt:
                    continue
                wid = f"cw{k}k{j}"
                glue = bool(spans) and (txt[:1] in "-'’" or prev_txt[-1:] in "'’")
                spans.append(("\x00" if glue else "") + f'<span id="{wid}" class="k">{html_escape(txt)}</span>')
                prev_txt = txt
                ws = tmap(words[m]["start"])
                if ws >= p["start"] + 0.04:
                    tweens.append(f'      tl.set("#{wid}", {{color: "{accent}"}}, {ws:.3f});')
                    tweens.append(f'      tl.fromTo("#{wid}", {{scale: 1.0}}, {{scale: 1.1, duration: 0.09, yoyo: true, repeat: 1, ease: "power1.out"}}, {ws:.3f});')
                else:
                    tweens.append(f'      tl.set("#{wid}", {{color: "{accent}"}}, {p["start"]:.3f});')
                we = min(tmap(words[m]["end"]) + 0.02, p["end"] - 0.01)
                if j < len(p["mots"]) - 1:
                    tweens.append(f'      tl.set("#{wid}", {{color: "#ffffff"}}, {we:.3f});')
            p["html"] = " ".join(spans).replace(" \x00", "")
        elif style == "barre":
            # titre barré d'un X rouge : le texte = tous les mots sauf le dernier, le X tombe sur le dernier
            # « x_mot » : le X tombe sur ce mot (hors page) ; sinon sur le dernier mot de la page
            shown = p["mots"] if p.get("x_mot") is not None else p["mots"][:-1]
            txt = " ".join(t for t in (corr.get(m, words[m]["text"]) for m in shown) if t)
            lines, tw, th = title_metrics(txt or p["text"], FS_BARRE)
            pad = 0.07 * tw
            x0, bw = 480 - tw / 2 - pad, tw + 2 * pad
            y0, bh = 0.06 * th, 0.88 * th
            ang = math.degrees(math.atan2(bh, bw))
            ln = math.hypot(bw, bh)
            p["xbars"] = [("a", x0, y0 + bh - 20, -ang), ("b", x0, y0 - 20, ang)]
            bars = "".join(f'<i id="xb{k}{n}" class="xb" style="left:{x:.0f}px;top:{y:.0f}px;width:{ln:.0f}px"></i>'
                           for n, x, y, _ in p["xbars"])
            p["html"] = "<br>".join(html_escape(l) for l in lines) + bars
            xm = p["x_mot"] if p.get("x_mot") is not None else p["mots"][-1]
            # le X doit se tracer pendant que le titre est encore à l'écran (au moins 0,45 s avant la fin)
            p["x_time"] = max(p["start"] + 0.25, min(tmap(words[xm]["start"]) - 0.05, p["end"] - 0.45))
        elif style == "tel":
            nom = p.get("nom") or (vo_nom.get(p["mots"][0], "") if p["mots"] else "")
            p["html"] = (f'<b class="qui">{html_escape(nom.upper())}</b>' if nom else "") + html_escape(p["text"])
        else:
            p["html"] = html_escape(p["text"])
        extra, pos = "", ""
        if style in ("impact", "barre"):
            # le mot plein cadre se place sous le menton (ou au-dessus de la tête), jamais sur le visage
            fb = face_box(talk, p["start"] + 0.1)
            if fb:
                x, y, w, h = fb
                top = y + h + 60 if y + h + 60 <= 1250 else max(120, y - 320)
            else:
                top = 790
            pos = f' style="padding-top: {top}px"'
            extra = " impactcap"
        caps.append(
            f'      <div id="cap{k}" class="clip cap{extra}" data-start="{p["start"]:.3f}" data-duration="{dur:.3f}" data-track-index="5"{pos}>'
            f'<span id="cw{k}" class="w {style}">{p["html"]}</span></div>'
        )
        if style == "impact":
            tweens.append(f'      tl.fromTo("#cw{k}", {{scale: 1.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.18, ease: "power4.out"}}, {p["start"]:.3f});')
        elif style == "barre":
            xt = p["x_time"]
            tweens.append(f'      tl.fromTo("#cw{k}", {{scale: 1.5, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.18, ease: "power4.out"}}, {p["start"]:.3f});')
            for i, (n, _, _, ang) in enumerate(p["xbars"]):
                tweens.append(f'      tl.set("#xb{k}{n}", {{rotation: {ang:.2f}, scaleX: 0, transformOrigin: "left center"}}, 0);')
                tweens.append(f'      tl.to("#xb{k}{n}", {{scaleX: 1, duration: 0.14, ease: "power3.out"}}, {xt + 0.10 * i:.3f});')
            tweens.append(f'      tl.fromTo("#cw{k}", {{scale: 1}}, {{scale: 1.04, duration: 0.08, yoyo: true, repeat: 1, ease: "power1.out"}}, {xt + 0.08:.3f});')
            cue("whoosh-short", xt - 0.04)
        elif style in ("box", "big"):
            tweens.append(f'      tl.fromTo("#cw{k}", {{scale: 0.7, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.16, ease: "back.out(2.5)"}}, {p["start"]:.3f});')
            if style == "box":
                cue("pop", p["start"] - 0.02)
        else:
            tweens.append(f'      tl.fromTo("#cw{k}", {{scale: 0.9, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.12, ease: "power2.out"}}, {p["start"]:.3f});')

    # --- autocollants : edit.json "stickers": [{"mot": 57, "svg": "fleur-de-lys", "sfx": "ping", "duree": 1.4}]
    sticker_html = []
    for n, st in enumerate(edit.get("stickers", [])):
        m = int(st["mot"])
        if m in cut_set(edit) or m >= len(words):
            continue
        svg = TEMPLATE_DIR / "stickers" / f'{st.get("svg", "fleur-de-lys")}.svg'
        if not svg.exists() and (TEMPLATE_DIR / "stickers" / f'{st.get("svg")}.png').exists():
            svg = TEMPLATE_DIR / "stickers" / f'{st.get("svg")}.png'
        if not svg.exists():
            log(f"sticker : {svg.name} introuvable")
            continue
        name = link(svg, f"sticker{n}{svg.suffix}")
        t0 = max(0.0, tmap(words[m]["start"]) - 0.05)
        sd = float(st.get("duree", 1.4))
        sticker_html.append(f'      <div id="stk{n}" class="clip sticker" data-start="{t0:.3f}" data-duration="{sd:.3f}" data-track-index="7">'
                            f'<img src="{name}" alt="" /></div>')
        if st.get("anim") == "entree":
            # personnage qui entre par la droite en bas, se penche, puis ressort
            sticker_html[-1] = sticker_html[-1].replace('class="clip sticker"', 'class="clip sticker entree"')
            tweens.append(f'      tl.fromTo("#stk{n} img", {{x: 520, rotation: 12}}, {{x: 0, rotation: -4, duration: 0.38, ease: "back.out(1.8)"}}, {t0:.3f});')
            tweens.append(f'      tl.to("#stk{n} img", {{rotation: 3, duration: 0.45, yoyo: true, repeat: 1, ease: "sine.inOut"}}, {t0 + 0.4:.3f});')
            tweens.append(f'      tl.to("#stk{n} img", {{x: 560, duration: 0.3, ease: "power2.in"}}, {t0 + sd - 0.32:.3f});')
        elif st.get("anim") == "traverse":
            # l'autocollant traverse l'écran de gauche à droite en sautillant (ex. souris qui court)
            sticker_html[-1] = sticker_html[-1].replace('class="clip sticker"', 'class="clip sticker traverse"')
            tweens.append(f'      tl.fromTo("#stk{n} img", {{x: -380}}, {{x: 1500, duration: {sd:.3f}, ease: "none"}}, {t0:.3f});')
            hops = max(2, int(sd / 0.16))
            tweens.append(f'      tl.fromTo("#stk{n} img", {{y: 0}}, {{y: -26, duration: 0.08, yoyo: true, repeat: {hops * 2 - 1}, ease: "sine.inOut"}}, {t0:.3f});')
        else:
            tweens.append(f'      tl.fromTo("#stk{n} img", {{scale: 0.3, rotation: -14, opacity: 0}}, {{scale: 1, rotation: 0, opacity: 1, duration: 0.32, ease: "back.out(2.2)"}}, {t0:.3f});')
            tweens.append(f'      tl.to("#stk{n} img", {{scale: 1.06, duration: 0.5, ease: "sine.inOut"}}, {t0 + 0.4:.3f});')
            tweens.append(f'      tl.to("#stk{n} img", {{scale: 0.6, opacity: 0, duration: 0.2, ease: "power2.in"}}, {t0 + sd - 0.22:.3f});')
        cue(st.get("sfx", "ping"), t0)

    # --- verdicts plein écran : edit.json "verdicts": [{"mot": 222, "type": "faux"}]
    # types : vrai, faux, mitige (vrai et faux), red, green (red flag / green flag) ; "texte" remplace le mot affiché
    VERDICTS = {
        "vrai": ("VRAI", "check", "chime"), "faux": ("FAUX", "x", "impact-bass-1"),
        "mitige": ('<span class="vd-v">VRAI</span><span class="vd-e">ET</span><span class="vd-x">FAUX</span>', "", "whoosh"),
        "red": ("RED<br>FLAG", "flag", "impact-bass-1"), "green": ("GREEN<br>FLAG", "flag", "chime"),
    }
    ICONS = {
        "check": '<circle class="vd-c" cx="60" cy="60" r="52"/><path class="vd-p" d="M34 62 L52 80 L87 42"/>',
        "x": '<circle class="vd-c" cx="60" cy="60" r="52"/><path class="vd-p" d="M40 40 L80 80 M80 40 L40 80"/>',
        "flag": '<path class="vd-p" d="M32 108 L32 14"/><path class="vd-f" d="M34 16 C52 6 66 26 90 16 L90 62 C66 72 52 52 34 62 Z"/>',
    }
    for n, vd in enumerate(edit.get("verdicts", [])):
        if "t" not in vd:
            m = int(vd["mot"])
            if m in cut_set(edit) or m >= len(words):
                continue
        kind = vd.get("type", "faux")
        mot, icon, vsfx = VERDICTS[kind]
        mot = vd.get("texte", mot)
        # "t" : temps de sortie imposé (ex. intro posée sur la pré-ouverture)
        t0 = float(vd["t"]) if "t" in vd else max(0.0, tmap(words[m]["start"]) - 0.08)
        vdur = float(vd.get("duree", 1.3))
        svg = f'<svg class="vd-ic" viewBox="0 0 120 120">{ICONS[icon]}</svg>' if icon else ""
        sticker_html.append(f'      <div id="vd{n}" class="clip verdict {kind}" data-start="{t0:.3f}" data-duration="{vdur:.3f}" data-track-index="8">'
                            f'<div class="vd-bg"></div><div class="vd-in">{svg}<div class="vd-mot">{mot}</div></div></div>')
        sel = f"#vd{n}"
        tweens.append(f'      tl.fromTo("{sel} .vd-bg", {{clipPath: "polygon(0 0, 0 0, 0 100%, 0 100%)"}}, {{clipPath: "polygon(0 0, 135% 0, 100% 100%, 0 100%)", duration: 0.24, ease: "power3.out"}}, {t0:.3f});')
        tweens.append(f'      tl.fromTo("{sel} .vd-mot", {{scale: 1.7, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.3, ease: "back.out(2.4)"}}, {t0 + 0.12:.3f});')
        if icon:
            tweens.append(f'      tl.fromTo("{sel} .vd-ic", {{scale: 0.4, rotation: -20, opacity: 0}}, {{scale: 1, rotation: 0, opacity: 1, duration: 0.3, ease: "back.out(2)"}}, {t0 + 0.08:.3f});')
            tweens.append(f'      tl.fromTo("{sel} .vd-c, {sel} .vd-p", {{strokeDashoffset: 340}}, {{strokeDashoffset: 0, duration: 0.34, ease: "power2.out", stagger: 0.08}}, {t0 + 0.12:.3f});')
        if kind in ("faux", "red"):
            tweens.append(f'      tl.to("{sel} .vd-in", {{x: 14, duration: 0.05, yoyo: true, repeat: 5, ease: "sine.inOut"}}, {t0 + 0.42:.3f});')
        elif kind in ("vrai", "green"):
            tweens.append(f'      tl.to("{sel} .vd-in", {{y: -18, duration: 0.14, yoyo: true, repeat: 1, ease: "power2.out"}}, {t0 + 0.42:.3f});')
        if kind in ("red", "green"):
            tweens.append(f'      tl.fromTo("{sel} .vd-f", {{skewY: 0}}, {{skewY: -12, scaleX: 0.92, duration: 0.16, yoyo: true, repeat: 5, ease: "sine.inOut", transformOrigin: "0% 50%"}}, {t0 + 0.3:.3f});')
        tweens.append(f'      tl.to("{sel} .vd-in", {{scale: 0.85, opacity: 0, duration: 0.18, ease: "power2.in"}}, {t0 + vdur - 0.24:.3f});')
        tweens.append(f'      tl.to("{sel} .vd-bg", {{clipPath: "polygon(100% 0, 135% 0, 100% 100%, 100% 100%)", duration: 0.22, ease: "power3.in"}}, {t0 + vdur - 0.22:.3f});')
        if vd.get("sfx", True):  # sans effet quand un jingle porte déjà l'intro
            cue("whoosh-short", t0 - 0.04)
            cue(vsfx, t0 + 0.12)

    # --- accroche
    hook = ""
    acc = edit.get("accroche") or {}
    if acc.get("texte"):
        h_end = tmap(words[min(int(acc.get("fin_mot", 8)), len(words) - 1)]["end"])
        h0 = float(acc.get("debut", 0.0))  # après une intro plein écran, l'accroche attend sa fin
        h_end = min(max(h_end, h0 + 3.5), max(talk_dur - 1.0, h0 + 3.5))  # jamais moins de 3,5 s à l'écran
        hook = (f'      <div id="hook" class="clip hook" data-start="{h0:.3f}" data-duration="{h_end - h0:.3f}" data-track-index="6">'
                f'<span id="hooktext" class="h">{hook_html(acc["texte"], 58)}</span></div>')
        tweens.append(f'      tl.fromTo("#hooktext", {{y: -30, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.35, ease: "power3.out"}}, {h0 + 0.15:.3f});')
        tweens.append(f'      tl.to("#hooktext", {{opacity: 0, y: -20, duration: 0.25, ease: "power2.in"}}, {max(0.0, h_end - 0.28):.3f});')
        if h0 == 0:
            cue("whoosh-short", 0.1)

    # --- appel à l'action à l'écran sur les 3 dernières secondes de parole
    cta_html = ""
    cta_txt = profile.get("cta_court") or ""
    if cta_txt and talk_dur > 8:
        c0 = talk_dur - 3.2
        cta_html = (f'      <div id="cta" class="clip cta" data-start="{c0:.3f}" data-duration="{talk_dur - c0:.3f}" data-track-index="7">'
                    f'<span id="ctapill" class="pill">{hook_html(cta_txt)}</span></div>')
        tweens.append(f'      tl.fromTo("#ctapill", {{y: 80, opacity: 0, scale: 0.9}}, {{y: 0, opacity: 1, scale: 1, duration: 0.35, ease: "back.out(1.6)"}}, {c0:.3f});')
        cue("pop", c0)

    # --- b-roll : vidéo ou photo (Ken Burns), whoosh à l'entrée et à la sortie, fondu court aux deux bouts
    broll_html = []
    for b in brolls:
        bid = f"broll{b['n']}"
        if b.get("type", "video") == "video":
            src = work / "broll" / b["file"]
        else:
            # photo locale : chemin mémorisé, sinon retrouvée dans l'index (banque broll ou produits du site)
            src = Path(b["path"]) if b.get("path") else next((Path(x["path"]) for x in load_broll_index(work) if x["file"] == b["file"]),
                                                              work.parent / "assets" / "broll" / b["file"])
        if vf_grade and b.get("type", "video") == "video" and str(b.get("origin", "")).startswith("local:"):
            graded = work / "broll" / b["file"].replace(".mp4", "_grade.mp4")
            if not graded.exists():
                sh(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", vf_grade, "-c:a", "copy", *h264("10M"),
                    "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-colorspace", "bt709", graded])
            src = graded
        name = link(src, b["file"])
        d = b["duration"]
        if b.get("type") == "photo":
            broll_html.append(f'      <img id="{bid}" class="clip broll" src="{name}" data-start="{b["start"]:.3f}" data-duration="{d:.3f}" data-track-index="1" />')
            tweens.append(f'      tl.fromTo("#{bid}", {{scale: 1.12, xPercent: 2}}, {{scale: 1.0, xPercent: -2, duration: {d:.3f}, ease: "none"}}, {b["start"]:.3f});')
        else:
            # b-roll muets par défaut ; le profil peut activer le son réel avec "broll_son": true
            snd = 'data-has-audio="true" data-volume="0.22"' if (b.get("audio") and profile.get("broll_son")) else "muted"
            broll_html.append(f'      <video id="{bid}" class="broll" src="{name}" data-start="{b["start"]:.3f}" data-duration="{d:.3f}" data-media-start="0" {snd} data-track-index="1"></video>')
            tweens.append(f'      tl.fromTo("#{bid}", {{scale: 1.0}}, {{scale: 1.08, duration: {d:.3f}, ease: "none"}}, {b["start"]:.3f});')
        # fondu de 5 images à l'entrée et à la sortie : la coupe se lit comme une transition, pas comme un accroc
        # fondus seulement vers le visage : entre deux b-roll enchaînés, coupe franche (sinon le
        # visage apparaît 0,2 s pendant que l'un s'éteint et que l'autre s'allume)
        prev_end = max([x["start"] + x["duration"] for x in brolls if x is not b and x["start"] < b["start"]] or [-9])
        next_start = min([x["start"] for x in brolls if x is not b and x["start"] > b["start"]] or [9e9])
        if b["start"] - prev_end > 0.25:
            tweens.append(f'      tl.fromTo("#{bid}", {{opacity: 0}}, {{opacity: 1, duration: 0.16, ease: "none"}}, {b["start"]:.3f});')
        if next_start - (b["start"] + d) > 0.25:
            tweens.append(f'      tl.to("#{bid}", {{opacity: 0, duration: 0.16, ease: "none"}}, {b["start"] + d - 0.2:.3f});')
        cue("whoosh-short", b["start"] - 0.1)

    # --- carte de fin
    endcard_html = ""
    total = talk_dur
    ec_cfg = profile.get("carte_fin") or {}
    if ec_cfg.get("type") == "logo" and ec_cfg.get("fichier"):
        logo = (ROOT / ec_cfg["fichier"]).resolve() if not Path(ec_cfg["fichier"]).is_absolute() else Path(ec_cfg["fichier"])
        if logo.exists():
            name = link(logo, "logo" + logo.suffix)
            ec_dur = float(ec_cfg.get("duree", 3.0))
            fond = ec_cfg.get("fond", "#000000")
            ligne = html_escape(ec_cfg.get("texte", profile.get("cta_defaut", "")))
            endcard_html = (
                f'      <div id="endcard" class="clip" data-start="{talk_dur:.3f}" data-duration="{ec_dur:.3f}" data-track-index="2" '
                f'style="background:{fond}; z-index:3; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:60px;">'
                f'<img id="endlogo" src="{name}" style="width:84%; max-height:40%; object-fit:contain;" />'
                f'<div id="endtext" style="color:#fff; font-weight:700; font-size:44px; text-align:center; padding:0 90px; letter-spacing:-0.01em;">{ligne}</div></div>'
            )
            tweens.append(f'      tl.fromTo("#endlogo", {{scale: 0.86, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.5, ease: "power3.out"}}, {talk_dur:.3f});')
            tweens.append(f'      tl.fromTo("#endtext", {{y: 24, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.45, ease: "power2.out"}}, {talk_dur + 0.35:.3f});')
            cue("whoosh", talk_dur - 0.12)
            total = talk_dur + ec_dur
            endcard = None
    if endcard and endcard.exists():
        ec_small = work / "endcard_1080.mp4"
        if not ec_small.exists():
            sh(["ffmpeg", "-v", "error", "-y", "-i", endcard,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30",
                "-an", *h264("10M"), "-pix_fmt", "yuv420p",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", ec_small])
        ec_dur = min(probe(ec_small)["duration"], 3.5)
        name = link(ec_small, "endcard.mp4")
        endcard_html = (f'      <video id="endcard" src="{name}" data-start="{talk_dur:.3f}" data-duration="{ec_dur:.3f}" '
                        f'data-media-start="0" muted data-track-index="2"></video>')
        cue("whoosh", talk_dur - 0.12)
        total = talk_dur + ec_dur

    # --- trame musicale : boucle du profil, bas sous la voix, montée sur la carte de fin, fondu final
    music_html = ""
    mus = profile.get("musique") or {}
    if mus.get("fichier"):
        loop = Path(mus["fichier"]).expanduser()
        if not loop.is_absolute():
            loop = ROOT / loop
        if loop.exists():
            m = work / "music.m4a"
            g_voice, g_end = float(mus.get("gain_voix", 0.08)), float(mus.get("gain_fin", 0.55))
            t_end = talk_dur if endcard_html else total
            # 1) boucle normalisée à -18 LUFS ; 2) répétée et coupée à la durée ; 3) enveloppe + fondus
            loop_dur = probe(loop)["duration"]
            reps = int(total / max(loop_dur, 1.0)) + 2
            sh(["ffmpeg", "-v", "error", "-y", "-stream_loop", str(reps), "-i", loop, "-t", f"{total + 0.5:.3f}",
                "-af", f"loudnorm=I=-18:TP=-2:LRA=9,"
                       f"volume='{g_voice}+({g_end}-{g_voice})*min(max((t-{t_end:.3f})/0.6,0),1)':eval=frame,"
                       f"afade=t=in:st=0:d=0.8,afade=t=out:st={max(0.0, total - 1.6):.3f}:d=1.5",
                "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "160k", m])
            name = link(m, "music.m4a")
            music_html = f'      <audio id="music" src="{name}" data-start="0" data-duration="{total:.3f}" data-volume="1" data-track-index="9"></audio>'
        else:
            log(f"musique : fichier introuvable {loop}")

    # --- effets sonores : chaque effet accompagne un mouvement visible, jamais deux effets à moins de
    #     1,1 s (priorité : impact > b-roll et recadrages > pops), plafond d'un effet par 3,5 s de vidéo
    prio = {"impact-bass-1": 0, "ping": 0, "chime": 0, "whoosh": 0, "whoosh-short": 1, "pop": 2, "click-soft": 3}
    kept = []
    for name, at in sorted(sfx, key=lambda x: (prio.get(x[0], 9), x[1])):
        if at < 0 or any(abs(at - t2) < 1.1 for _, t2 in kept):
            continue
        kept.append((name, at))
    budget = max(3, int(total / 3.5))
    kept = sorted(kept, key=lambda x: (prio.get(x[0], 9), x[1]))[:budget]
    sfx_html = []
    for n, (name, at) in enumerate(sorted(kept, key=lambda x: x[1])):
        shutil.copy2(SFX_DIR / f"{name}.mp3", comp / "sfx" / f"{name}.mp3")
        sfx_html.append(f'      <audio id="sfx{n}" src="sfx/{name}.mp3" data-start="{at:.3f}" data-volume="{SFX_VOL.get(name, 0.3)}" data-track-index="8"></audio>')

    html = (TEMPLATE_DIR / "index.template.html").read_text()
    repl = {
        "{{TITLE}}": html_escape(title),
        "{{DURATION}}": f"{total:.3f}",
        "{{TALK_SRC}}": talk_name,
        "{{TALK_DURATION}}": f"{talk_dur:.3f}",
        "{{BROLL}}": "\n".join(broll_html),
        "{{ENDCARD}}": endcard_html,
        "{{HOOK}}": hook + ("\n" + "\n".join(sticker_html) if sticker_html else ""),
        "{{CTA}}": cta_html,
        "{{CAPTIONS}}": "\n".join(caps),
        "{{SFX}}": "\n".join(sfx_html + [music_html]),
        "{{TWEENS}}": "\n".join(tweens),
        "{{CAP_TOP}}": "1120",
        "{{FS_NORMAL}}": "72",
        "{{FS_BIG}}": "104",
        "{{FS_SCRIPT}}": "108",
        "{{FS_BOX}}": "80",
        "{{FS_IMPACT}}": "120",
        "{{FS_BARRE}}": str(FS_BARRE),
        "{{ACCENT}}": profile.get("couleur_marque", "#E8843C"),
    }
    for k, v in repl.items():
        html = html.replace(k, v)
    (comp / "index.html").write_text(html)
    (comp / "meta.json").write_text(json.dumps({"id": "main", "name": title}))
    (comp / "hyperframes.json").write_text(json.dumps({"media": {"autoProxy": False}}))
    log(f"compose : {len(segs)} segments ({src_dur:.1f}s -> {talk_dur:.1f}s), {len(pages)} pages, "
        f"{len(brolls)} b-roll, {len(sfx_html)} effets sonores, musique {'oui' if music_html else 'non'}, "
        f"durée {total:.1f}s -> {comp / 'index.html'}")
    return comp


# ----------------------------------------------------------------------- 7. render
def step_render(comp: Path, work: Path, profile: dict, title_slug: str, mois: str) -> Path:
    raw = work / "render_raw.mp4"
    env = dict(os.environ)
    # --gpu accélère le rendu sur Mac ; ailleurs il dépend du pilote, on le laisse à HF_GPU=1
    gpu = " --gpu" if MAC_ARM or os.environ.get("HF_GPU") == "1" else ""
    cmd, kw = commande_hyperframes(f'render . -o "{raw}" --fps 30 --quality looks --sdr{gpu} --quiet', comp)
    log("$ hyperframes render")
    subprocess.run(cmd, check=True, env=env, **kw)
    OUT_DIR.joinpath(profile["id"]).mkdir(parents=True, exist_ok=True)
    final = OUT_DIR / profile["id"] / f"{mois}_{title_slug}.mp4"
    if final.exists():
        n = 2
        while (OUT_DIR / profile["id"] / f"{mois}_{title_slug}_V{n}.mp4").exists():
            n += 1
        final = OUT_DIR / profile["id"] / f"{mois}_{title_slug}_V{n}.mp4"
    sh(["ffmpeg", "-v", "error", "-y", "-i", raw,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", final])
    # planche de contact pour la révision
    sheet = final.with_suffix(".planche.jpg")
    dur = probe(final)["duration"]
    step = max(1.0, dur / 12)
    sh(["ffmpeg", "-v", "error", "-y", "-i", final,
        "-vf", f"select='not(mod(n\\,{int(step * 30)}))',scale=270:-1,tile=6x2", "-vsync", "vfr", "-frames:v", "1", "-q:v", "3", sheet])
    log(f"render : {final}")
    return final


# -------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client", required=True)
    ap.add_argument("--rush", required=True, type=Path, nargs="+",
                    help="un rush, ou plusieurs enchaînés dans l'ordre donné")
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--brief", type=Path)
    ap.add_argument("--mois", default=dt.date.today().strftime("%Y-%m"))
    ap.add_argument("--jusqua", choices=STEPS, default="render")
    ap.add_argument("--llm", default=None, help="fournisseur de l'édito : claude-cli, anthropic, gemini, openai (défaut : LLM_PROVIDER ou claude-cli)")
    ap.add_argument("--model", default=None, help="modèle de l'édito (défaut selon le fournisseur, ou LLM_MODEL)")
    ap.add_argument("--sans-broll", action="store_true")
    ap.add_argument("--rotation", choices=["auto", "none", "cw", "ccw"], default="auto",
                    help="orientation d'un rush en paysage sans métadonnée (auto = vote de visages)")
    ap.add_argument("--langue", choices=["fr", "en"], default=None,
                    help="langue du reel (défaut : profil) ; en = transcription, accroche, pilule et carte de fin anglaises")
    ap.add_argument("--lut", default="auto",
                    help="auto (détecte le S-Log), none, slog3, ou chemin d'un .cube")
    args = ap.parse_args()

    profile = load_profile(args.client)
    if args.langue:
        profile["langue"] = args.langue
    if str(profile.get("langue", "fr")).lower().startswith("en"):
        profile["cta_court"] = profile.get("cta_court_en", profile.get("cta_court", ""))
        profile["carte_fin"] = profile.get("carte_fin_en", profile.get("carte_fin"))
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    brief = args.brief.read_text() if args.brief and args.brief.exists() else ""
    last = STEPS.index(args.jusqua)

    if (work / "rush_cut.mp4").exists():
        # le rush brut et sa version normalisée ont pu être effacés pour libérer le disque :
        # tout ce qui suit part de rush_cut.mp4
        norm = work / "rush_1080.mp4"
        log("normalize : rush_cut.mp4 présent, étape sautée")
    elif len(args.rush) == 1:
        norm = step_normalize(args.rush[0].resolve(), work, args.rotation, args.lut)
    else:
        norm = work / "rush_1080.mp4"
        if not norm.exists():
            rotation = args.rotation
            if rotation == "auto":
                # même tournage, même orientation : on additionne les votes de tous les rushs
                total = {"": 0, "transpose=1": 0, "transpose=2": 0}
                for r in args.rush:
                    sc = rotation_scores(r.resolve())
                    if sc:
                        for k, v in sc.items():
                            total[k] += v
                best = max(total, key=total.get)
                rotation = {"": "none", "transpose=1": "cw", "transpose=2": "ccw"}[best if total[best] > 0 else ""]
                log(f"normalize : orientation commune aux {len(args.rush)} rushs {total} -> {rotation}")
            parts = []
            for i, r in enumerate(args.rush):
                sub = work / f"_part{i:02d}"
                sub.mkdir(exist_ok=True)
                parts.append(step_normalize(r.resolve(), sub, rotation, args.lut))
            lst = work / "_parts.txt"
            lst.write_text("".join(f"file '{p}'\n" for p in parts))
            sh(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", norm])
            log(f"normalize : {len(parts)} rushs enchaînés")
    if last < 1:
        return
    cut = (work / "rush_cut.mp4") if (work / "rush_cut.mp4").exists() else step_cut(norm, work)
    if last < 2:
        return
    words = step_transcribe(cut, work, profile)
    if last < 3:
        return
    edit = step_edito(words, work, profile, brief, args.model, args.llm)
    if last < 4:
        return
    if args.sans_broll:
        broll = work / "broll.json"
        broll.write_text("[]")
    else:
        broll = step_broll(edit, words, work, profile)
    if last < 5:
        return
    e = json.loads(edit.read_text())
    title_slug = slugify(e.get("titre_slug", work.name))
    endcard = None
    ec = profile.get("carte_fin", {})
    if ec.get("type") == "video" and ec.get("fichier"):
        endcard = (ROOT / ec["fichier"]).resolve()
    comp = step_compose(work, profile, edit, words, broll, cut, endcard, title_slug)
    if last < 6:
        return
    step_render(comp, work, profile, title_slug, args.mois)


if __name__ == "__main__":
    main()
