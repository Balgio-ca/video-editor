"""Génère par IA les médias qui manquent à un montage : voix, effets sonores, musique, images et vidéos de b-roll.

Chaque sous-commande écrit un fichier, affiche son chemin et dit comment s'en servir dans edit.json
ou dans le profil client. Les clés sont lues dans l'environnement (ou dans .env à la racine du dépôt).

Sous-commandes

  voix "texte" --sortie chemin.mp3 [--voix VOICE_ID] [--modele eleven_multilingual_v2]
      Synthèse vocale ElevenLabs. Voix par défaut : ELEVENLABS_VOICE_ID, sinon --voix est exigé.
      Sert à une voix off, une question enregistrée ou une narration posée en « preroll » d'edit.json.
  voix --liste [--recherche mot]
      Liste les voix du compte ElevenLabs : voice_id, nom, langue et accent.

  son "description" --nom ding [--duree 1.5] [--client CLIENT]
      Effet sonore ElevenLabs, écrit dans sons/<nom>.mp3 (ou work/<client>/assets/sons/<nom>.mp3 avec
      --client). Il s'utilise aussitôt par son nom dans edit.json (« sons », « stickers », « verdicts »).
      Pour un jingle court de 2 ou 3 s, ce modèle d'effets sonores réussit mieux que le modèle de musique.

  musique "description" --sortie chemin.mp3 --duree 30
      Musique ElevenLabs (point d'accès /v1/music), à poser dans « musique.fichier » du profil client.
      C'est le point d'accès le moins certain de ce fichier : en cas d'erreur 404, vérifier la
      documentation ElevenLabs (https://elevenlabs.io/docs) pour le chemin et les champs actuels.

  image "prompt" --client CLIENT --nom ID [--fournisseur openai|gemini] [--format portrait]
      Image de b-roll (OpenAI gpt-image-1 ou Gemini), écrite dans work/<client>/assets/broll/generes/<id>.png
      et ajoutée à work/<client>/assets/broll/index.json sous l'id « gen-<id> ».
  video "prompt" --client CLIENT --nom ID [--fournisseur gemini|openai] [--duree 5] [--delai 900]
      Vidéo de b-roll (Gemini Veo ou OpenAI Sora), convertie en 1080x1920 à 30 i/s sans son dans
      work/<client>/assets/broll/generes/<id>.mp4 et ajoutée à index.json sous l'id « gen-<id> ».
      Dans edit.json, le b-roll se cite alors par "source": "local:gen-<id>".

  Les images et vidéos IA ne servent que quand aucun clip du client ni de Pexels ne montre ce qui est dit.
  Jamais pour montrer un produit du client : un produit se montre avec une vraie photo.

Variables d'environnement

  ELEVENLABS_API_KEY   voix, effets sonores et musique (https://elevenlabs.io, en-tête xi-api-key)
  ELEVENLABS_VOICE_ID  voix par défaut de la sous-commande voix (facultatif)
  OPENAI_API_KEY       images gpt-image-1 et vidéos Sora
  GEMINI_API_KEY       images Gemini et vidéos Veo
  IMAGE_PROVIDER       fournisseur d'images par défaut : openai ou gemini (défaut : openai)
  IMAGE_MODEL          modèle d'images (défaut : gpt-image-1 ou gemini-2.5-flash-image)
  VIDEO_GEN_PROVIDER   fournisseur de vidéos par défaut : gemini ou openai (défaut : gemini)
  VIDEO_MODEL          modèle de vidéos (défaut : veo-3.0-fast-generate-001 ou sora-2)

Exemples

  python pipeline/generer.py voix --liste --recherche french
  python pipeline/generer.py voix "Vous cherchez un plancher pour votre sous-sol ?" --sortie work/exemple-plancher/assets/voix/question.mp3
  python pipeline/generer.py son "petit ding de caisse enregistreuse" --nom caisse --duree 1
  python pipeline/generer.py son "jingle de trois notes, xylophone joyeux" --nom jingle-intro --duree 2.5 --client exemple-plancher
  python pipeline/generer.py musique "lo-fi chaleureux, guitare douce, 90 bpm, sans voix" --sortie work/exemple-plancher/assets/musique/lofi.mp3 --duree 30
  python pipeline/generer.py image "sous-sol inondé, eau sur un plancher de bois, lumière froide" --client exemple-plancher --nom sous-sol-inonde
  python pipeline/generer.py video "enfant qui souffle les bougies d'un gâteau, fête colorée" --client exemple-plancher --nom bougies --fournisseur gemini
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plateforme import h264, outil  # noqa: E402  (l'import charge aussi .env)

ROOT = Path(__file__).resolve().parent.parent
ELEVEN = "https://api.elevenlabs.io"
OPENAI = "https://api.openai.com/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 300
SONDAGE = 10  # secondes entre deux interrogations d'une génération vidéo
FORMATS = {  # taille OpenAI, consigne de cadrage pour Gemini
    "portrait": ("1024x1536", "Image verticale au format 9:16, cadrée pour un reel."),
    "carre": ("1024x1024", "Image carrée au format 1:1."),
    "paysage": ("1536x1024", "Image horizontale au format 16:9."),
}
SORA_DUREES = (4, 8, 12)  # durées acceptées par sora-2


# ------------------------------------------------------------------ clés et HTTP
USAGES = {
    "ELEVENLABS_API_KEY": "générer les voix, effets sonores et musiques ElevenLabs",
    "OPENAI_API_KEY": "générer les images gpt-image-1 et les vidéos Sora d'OpenAI",
    "GEMINI_API_KEY": "générer les images Gemini et les vidéos Veo de Google",
}


def _cle(nom: str) -> str:
    cle = os.environ.get(nom, "")
    if not cle:
        raise SystemExit(f"{nom} manquante : elle sert à {USAGES[nom]}. L'ajouter dans .env (voir .env.example).")
    return cle


def _requete(methode: str, url: str, headers: dict, payload: dict | None = None, timeout: int = TIMEOUT,
             formulaire: dict | None = None):
    """Requête HTTP ; `formulaire` envoie les champs en multipart/form-data au lieu de JSON."""
    import requests

    if formulaire is not None:
        r = requests.request(methode, url, headers=headers, files={k: (None, str(v)) for k, v in formulaire.items()},
                             timeout=timeout)
    else:
        r = requests.request(methode, url, headers=headers, json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise SystemExit(f"{url} a répondu {r.status_code} :\n{r.text[:800]}")
    return r


def _ecrire(chemin: Path, contenu: bytes) -> Path:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    return chemin


def _relatif(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def _chemin(sortie: str) -> Path:
    p = Path(sortie).expanduser()
    return p if p.is_absolute() else Path.cwd() / p


# ------------------------------------------------------------------ b-roll du client
def dossier_broll(client: str) -> Path:
    """work/<client>/assets/broll ; le dossier du client doit déjà exister (évite une faute de frappe muette)."""
    d = ROOT / "work" / client
    if not d.is_dir():
        existants = sorted(p.name for p in (ROOT / "work").iterdir() if p.is_dir()) if (ROOT / "work").is_dir() else []
        raise SystemExit(f"client « {client} » introuvable dans work/ ; existants : {', '.join(existants) or 'aucun'}")
    return d / "assets" / "broll"


def ajouter_index(broll: Path, entree: dict) -> Path:
    """Ajoute (ou remplace, à id égal) une entrée dans broll/index.json, créé au besoin."""
    index = broll / "index.json"
    items = json.loads(index.read_text(encoding="utf-8")) if index.exists() else []
    items = [b for b in items if b.get("id") != entree["id"]] + [entree]
    broll.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return index


def _annoncer_broll(fichier: Path, index: Path, id_: str) -> None:
    print(f"écrit : {_relatif(fichier)}")
    print(f"ajouté à {_relatif(index)} sous l'id « {id_} »")
    print(f'dans edit.json, en b-roll :  "source": "local:{id_}"')


# ------------------------------------------------------------------ ElevenLabs
def _eleven(chemin: str, payload: dict | None = None, methode: str = "POST"):
    return _requete(methode, f"{ELEVEN}{chemin}", {"xi-api-key": _cle("ELEVENLABS_API_KEY")}, payload)


def cmd_voix(a) -> None:
    if a.liste:
        voix = _eleven("/v1/voices", methode="GET").json().get("voices", [])
        mot = (a.recherche or "").lower()
        for v in voix:
            labels = v.get("labels") or {}
            infos = " / ".join(str(labels[k]) for k in ("language", "accent", "gender", "age") if labels.get(k))
            ligne = f"{v.get('voice_id')}  {v.get('name')}  {infos}"
            if not mot or mot in ligne.lower() or mot in json.dumps(labels, ensure_ascii=False).lower():
                print(ligne)
        return
    if not a.texte or not a.sortie:
        raise SystemExit("voix : donner le texte et --sortie chemin.mp3 (ou --liste pour voir les voix)")
    voice_id = a.voix or os.environ.get("ELEVENLABS_VOICE_ID", "")
    if not voice_id:
        raise SystemExit("voix : préciser --voix VOICE_ID ou définir ELEVENLABS_VOICE_ID (liste : generer.py voix --liste)")
    r = _eleven(f"/v1/text-to-speech/{voice_id}", {"text": a.texte, "model_id": a.modele})
    out = _ecrire(_chemin(a.sortie), r.content)
    print(f"écrit : {_relatif(out)}")
    print(f'dans edit.json, en pré-ouverture :  "preroll": {{"audio": "{_relatif(out)}", "image_de": "avant"}}')


def cmd_son(a) -> None:
    payload = {"text": a.description}
    if a.duree is not None:
        payload["duration_seconds"] = a.duree
    dossier = (dossier_broll(a.client).parent / "sons") if a.client else ROOT / "sons"
    out = _ecrire(dossier / f"{a.nom}.mp3", _eleven("/v1/sound-generation", payload).content)
    print(f"écrit : {_relatif(out)}")
    print(f"utilisable aussitôt par son nom « {a.nom} » dans edit.json (« sons », « stickers », « verdicts »)")


def cmd_musique(a) -> None:
    r = _eleven("/v1/music", {"prompt": a.description, "music_length_ms": int(a.duree * 1000)})
    out = _ecrire(_chemin(a.sortie), r.content)
    print(f"écrit : {_relatif(out)}")
    print(f'dans le profil client :  "musique": {{"fichier": "{_relatif(out)}"}}')


# ------------------------------------------------------------------ images
def _image_openai(prompt: str, fmt: str) -> bytes:
    data = _requete("POST", f"{OPENAI}/images/generations", {"Authorization": f"Bearer {_cle('OPENAI_API_KEY')}"},
                    {"model": os.environ.get("IMAGE_MODEL") or "gpt-image-1", "prompt": prompt,
                     "size": FORMATS[fmt][0], "n": 1}).json()
    return base64.b64decode(data["data"][0]["b64_json"])


def _image_gemini(prompt: str, fmt: str) -> bytes:
    modele = os.environ.get("IMAGE_MODEL") or "gemini-2.5-flash-image"
    data = _requete("POST", f"{GEMINI}/models/{modele}:generateContent", {"x-goog-api-key": _cle("GEMINI_API_KEY")},
                    {"contents": [{"role": "user", "parts": [{"text": f"{prompt}\n\n{FORMATS[fmt][1]}"}]}],
                     "generationConfig": {"responseModalities": ["IMAGE"]}}).json()
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    for p in parts:
        inline = p.get("inlineData") or p.get("inline_data")
        if inline and inline.get("data"):
            brut = base64.b64decode(inline["data"])
            if "png" in (inline.get("mimeType") or inline.get("mime_type") or "png"):
                return brut
            # autre format (jpeg, webp) : converti en PNG pour garder le nom de fichier promis
            return subprocess.run([outil("ffmpeg"), "-v", "error", "-i", "pipe:0", "-f", "image2pipe", "-c:v", "png", "pipe:1"],
                                  input=brut, capture_output=True, check=True).stdout
    raise SystemExit(f"Gemini n'a renvoyé aucune image :\n{json.dumps(data, ensure_ascii=False)[:800]}")


def cmd_image(a) -> None:
    fournisseur = (a.fournisseur or os.environ.get("IMAGE_PROVIDER") or "openai").lower()
    if fournisseur not in ("openai", "gemini"):
        raise SystemExit(f"fournisseur d'images inconnu « {fournisseur} » ; choix : openai, gemini")
    broll = dossier_broll(a.client)
    _cle("OPENAI_API_KEY" if fournisseur == "openai" else "GEMINI_API_KEY")
    print(f"génération de l'image ({fournisseur})...")
    brut = (_image_openai if fournisseur == "openai" else _image_gemini)(a.prompt, a.format)
    out = _ecrire(broll / "generes" / f"{a.nom}.png", brut)
    id_ = f"gen-{a.nom}"
    index = ajouter_index(broll, {"id": id_, "file": f"generes/{a.nom}.png", "type": "photo",
                                  "description": f"{a.prompt} (image générée par IA)", "tags": ["généré"]})
    _annoncer_broll(out, index, id_)


# ------------------------------------------------------------------ vidéos
def _attendre(interroger, delai: int, fournisseur: str):
    """Appelle interroger() toutes les SONDAGE secondes jusqu'à un résultat non nul, ou SystemExit au délai."""
    debut = time.monotonic()
    while True:
        res = interroger()
        if res is not None:
            return res
        ecoule = time.monotonic() - debut
        if ecoule > delai:
            raise SystemExit(f"{fournisseur} : délai de {delai} s dépassé ; relancer avec --delai plus long")
        print(f"  en cours... {ecoule:.0f} s", flush=True)
        time.sleep(SONDAGE)


def _video_gemini(prompt: str, duree: float, delai: int, brut: Path) -> None:
    import requests

    cle = {"x-goog-api-key": _cle("GEMINI_API_KEY")}
    modele = os.environ.get("VIDEO_MODEL") or "veo-3.0-fast-generate-001"
    op = _requete("POST", f"{GEMINI}/models/{modele}:predictLongRunning", cle,
                  {"instances": [{"prompt": prompt}], "parameters": {"aspectRatio": "9:16"}}).json()
    nom = op["name"]

    def interroger():
        o = _requete("GET", f"{GEMINI}/{nom}", cle).json()
        if not o.get("done"):
            return None
        if o.get("error"):
            raise SystemExit(f"Veo a échoué :\n{json.dumps(o['error'], ensure_ascii=False)[:800]}")
        return o

    o = _attendre(interroger, delai, "Veo")
    try:
        uri = o["response"]["generateVideoResponse"]["generatedSamples"][0]["video"]["uri"]
    except (KeyError, IndexError):
        raise SystemExit(f"Veo n'a renvoyé aucune vidéo (filtre de contenu ?) :\n{json.dumps(o, ensure_ascii=False)[:800]}")
    r = requests.get(uri, headers=cle, timeout=TIMEOUT, allow_redirects=True)
    if r.status_code >= 400:
        raise SystemExit(f"téléchargement Veo : {r.status_code}\n{r.text[:800]}")
    _ecrire(brut, r.content)


def _video_openai(prompt: str, duree: float, delai: int, brut: Path) -> None:
    cle = {"Authorization": f"Bearer {_cle('OPENAI_API_KEY')}"}
    secondes = min(SORA_DUREES, key=lambda s: abs(s - duree))
    if secondes != duree:
        print(f"Sora accepte {', '.join(map(str, SORA_DUREES))} s : durée ramenée à {secondes} s")
    # l'API vidéo d'OpenAI attend un formulaire multipart, pas du JSON
    v = _requete("POST", f"{OPENAI}/videos", cle,
                 formulaire={"model": os.environ.get("VIDEO_MODEL") or "sora-2", "prompt": prompt,
                             "size": "720x1280", "seconds": str(secondes)}).json()

    def interroger():
        e = _requete("GET", f"{OPENAI}/videos/{v['id']}", cle).json()
        if e.get("status") == "failed":
            raise SystemExit(f"Sora a échoué :\n{json.dumps(e.get('error') or e, ensure_ascii=False)[:800]}")
        return e if e.get("status") == "completed" else None

    _attendre(interroger, delai, "Sora")
    _ecrire(brut, _requete("GET", f"{OPENAI}/videos/{v['id']}/content", cle).content)


def duree_video(p: Path) -> float:
    r = subprocess.run([outil("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(p)], capture_output=True, text=True, check=True)
    return round(float(r.stdout.strip()), 2)


def cmd_video(a) -> None:
    fournisseur = (a.fournisseur or os.environ.get("VIDEO_GEN_PROVIDER") or "gemini").lower()
    if fournisseur not in ("gemini", "openai"):
        raise SystemExit(f"fournisseur de vidéos inconnu « {fournisseur} » ; choix : gemini, openai")
    broll = dossier_broll(a.client)
    _cle("GEMINI_API_KEY" if fournisseur == "gemini" else "OPENAI_API_KEY")
    gen = broll / "generes"
    brut, out = gen / f"_{a.nom}_brut.mp4", gen / f"{a.nom}.mp4"
    print(f"génération de la vidéo ({fournisseur}), souvent une à plusieurs minutes...")
    (_video_gemini if fournisseur == "gemini" else _video_openai)(a.prompt, a.duree, a.delai, brut)
    print("conversion en 1080x1920, 30 i/s, sans son...")
    subprocess.run([outil("ffmpeg"), "-v", "error", "-y", "-i", str(brut),
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1",
                    "-an", *h264("10M"), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    brut.unlink(missing_ok=True)
    id_ = f"gen-{a.nom}"
    index = ajouter_index(broll, {"id": id_, "file": f"generes/{a.nom}.mp4", "type": "video", "duree": duree_video(out),
                                  "description": f"{a.prompt} (vidéo générée par IA)", "tags": ["généré"]})
    _annoncer_broll(out, index, id_)


# ------------------------------------------------------------------ ligne de commande
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Génère par IA voix, effets sonores, musique, images et vidéos de b-roll.",
                                 epilog="Détails et exemples : en tête de pipeline/generer.py.")
    sub = ap.add_subparsers(dest="commande", required=True)

    p = sub.add_parser("voix", help="synthèse vocale ElevenLabs, ou liste des voix")
    p.add_argument("texte", nargs="?", help="texte à dire")
    p.add_argument("--sortie", help="fichier .mp3 à écrire")
    p.add_argument("--voix", help="voice_id ElevenLabs (défaut : ELEVENLABS_VOICE_ID)")
    p.add_argument("--modele", default="eleven_multilingual_v2", help="modèle de voix (défaut : %(default)s)")
    p.add_argument("--liste", action="store_true", help="lister les voix du compte")
    p.add_argument("--recherche", help="avec --liste : ne garder que les voix qui contiennent ce mot")
    p.set_defaults(fn=cmd_voix)

    p = sub.add_parser("son", help="effet sonore ElevenLabs, utilisable par son nom dans edit.json")
    p.add_argument("description", help="description de l'effet, ex. « petit ding de caisse enregistreuse »")
    p.add_argument("--nom", required=True, help="nom de l'effet (fichier <nom>.mp3)")
    p.add_argument("--duree", type=float, help="durée en secondes (facultatif ; sinon choisie par le modèle)")
    p.add_argument("--client", help="ranger dans work/<client>/assets/sons/ plutôt que dans sons/")
    p.set_defaults(fn=cmd_son)

    p = sub.add_parser("musique", help="musique ElevenLabs pour « musique.fichier » du profil client")
    p.add_argument("description", help="style, instruments, tempo, ambiance")
    p.add_argument("--sortie", required=True, help="fichier .mp3 à écrire")
    p.add_argument("--duree", type=float, default=30, help="durée en secondes (défaut : %(default)s)")
    p.set_defaults(fn=cmd_musique)

    p = sub.add_parser("image", help="image de b-roll générée, ajoutée à index.json du client")
    p.add_argument("prompt", help="ce que montre l'image (jamais un produit du client)")
    p.add_argument("--client", required=True, help="dossier du client dans work/")
    p.add_argument("--nom", required=True, help="identifiant du fichier ; l'entrée d'index sera gen-<nom>")
    p.add_argument("--fournisseur", choices=("openai", "gemini"), help="défaut : IMAGE_PROVIDER, sinon openai")
    p.add_argument("--format", choices=tuple(FORMATS), default="portrait", help="cadrage (défaut : %(default)s)")
    p.set_defaults(fn=cmd_image)

    p = sub.add_parser("video", help="vidéo de b-roll générée, convertie en 1080x1920 et ajoutée à index.json")
    p.add_argument("prompt", help="ce que montre la vidéo (jamais un produit du client)")
    p.add_argument("--client", required=True, help="dossier du client dans work/")
    p.add_argument("--nom", required=True, help="identifiant du fichier ; l'entrée d'index sera gen-<nom>")
    p.add_argument("--fournisseur", choices=("gemini", "openai"), help="défaut : VIDEO_GEN_PROVIDER, sinon gemini")
    p.add_argument("--duree", type=float, default=5, help="durée visée en secondes, pour Sora (défaut : %(default)s)")
    p.add_argument("--delai", type=int, default=900, help="attente maximale de la génération en secondes (défaut : %(default)s)")
    p.set_defaults(fn=cmd_video)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
