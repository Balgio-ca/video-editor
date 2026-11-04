"""Un projet = un lot de reels pour un client, décrit par work/<projet>/sujets.json :

{
  "_projet": {"client": "mon-client", "mois": "2026-11"},
  "promo-hiver": {"rushs": ["C0040.MP4", "C0041.MP4"], "motif": "Promo-Hiver"},
  "gros-deal": {"rushs": ["C0011.MP4"], "motif": "Gros-Deal", "lut": "none", "langue": "fr"},
  "faq-2": {"rushs": ["../faq/src/C0032.MP4"], "motif": "FAQ-2"}
}

Chaque sujet a son dossier work/<projet>/<sujet>/ (brief.txt, src/, puis les fichiers du pipeline).
Un rush sans « / » est cherché dans <sujet>/src/ ; sinon le chemin est relatif au dossier du projet,
ce qui permet à plusieurs sujets de partager un même rush (une entrevue découpée en plusieurs reels).
Clés d'un sujet : rushs, motif (début du nom du fichier final), et au besoin client, mois, langue, lut, rotation.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def dossier(projet: str) -> Path:
    d = ROOT / "work" / projet
    if not (d / "sujets.json").exists():
        sys.exit(f"{d / 'sujets.json'} introuvable")
    return d


def sujets(projet: str) -> dict:
    data = json.loads((dossier(projet) / "sujets.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def sujet(projet: str, slug: str) -> dict:
    """Réglages d'un sujet, complétés par ceux du projet, avec les chemins des rushs résolus."""
    d = dossier(projet)
    data = json.loads((d / "sujets.json").read_text(encoding="utf-8"))
    if slug not in data:
        sys.exit(f"sujet « {slug} » absent de {d / 'sujets.json'}")
    s = {"langue": "fr", "lut": "auto", "rotation": "auto", **data.get("_projet", {}), **data[slug]}
    for k in ("client", "mois", "motif"):
        if not s.get(k):
            sys.exit(f"« {k} » manque pour {slug} (dans le sujet ou dans _projet)")
    s["work"] = d / slug
    s["rushs"] = [str(d / r) if "/" in r else str(d / slug / "src" / r) for r in s.get("rushs", [])]
    return s


def rendu(s: dict) -> Path | None:
    """Fichier final d'un sujet dans out/<client>/, s'il existe."""
    found = sorted(glob.glob(str(ROOT / "out" / s["client"] / f"{s['mois']}_{s['motif']}*.mp4")))
    return Path(found[0]) if found else None
