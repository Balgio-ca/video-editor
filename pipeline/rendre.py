#!/usr/bin/env python3
"""Monte un sujet d'un projet avec les réglages de work/<projet>/sujets.json.

  rendre.py <projet> <sujet>                 refait b-roll manquant, composition et rendu
  rendre.py <projet> <sujet> --broll         refait aussi la recherche de b-roll
  rendre.py <projet> <sujet> --jusqua edito  s'arrête après l'édito (premier passage d'un lot)
  rendre.py <projet> --tous [--jusqua edito] tous les sujets du projet, l'un après l'autre

Les options --llm et --model passent à reel.py (fournisseur et modèle de l'édito).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projet as P  # noqa: E402
import plateforme  # noqa: E402,F401  (charge .env)

ROOT = P.ROOT
GARDE = re.compile(r"^\[reel\] (normalize|transcribe|edito|broll [0-9]+ : (étiré|raccourci)|compose|render)|Traceback|rror:")


def un(projet: str, slug: str, args) -> int:
    s = P.sujet(projet, slug)
    w = s["work"]
    if args.broll:
        (w / "broll.json").unlink(missing_ok=True)
    if args.jusqua != "edito":
        # refait la composition et le rendu final ; les étapes en amont restent en cache
        (w / "comp" / "index.html").unlink(missing_ok=True)
        for f in (ROOT / "out" / s["client"]).glob(f"{s['mois']}_{s['motif']}*"):
            f.unlink()
    cmd = [sys.executable, str(ROOT / "pipeline" / "reel.py"),
           "--client", s["client"], "--rush", *s["rushs"], "--work", str(w), "--mois", s["mois"],
           "--langue", s["langue"], "--lut", s["lut"], "--rotation", s["rotation"]]
    if (w / "brief.txt").exists():
        cmd += ["--brief", str(w / "brief.txt")]
    if args.jusqua:
        cmd += ["--jusqua", args.jusqua]
    if args.llm:
        cmd += ["--llm", args.llm]
    if args.model:
        cmd += ["--model", args.model]
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        if args.verbeux or GARDE.search(line):
            print(f"[{slug}] {line}", end="")
    return p.wait()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projet")
    ap.add_argument("sujet", nargs="?")
    ap.add_argument("--tous", action="store_true")
    ap.add_argument("--broll", action="store_true")
    ap.add_argument("--jusqua", choices=["normalize", "cut", "transcribe", "edito", "broll", "compose", "render"])
    ap.add_argument("--llm")
    ap.add_argument("--model")
    ap.add_argument("--verbeux", action="store_true", help="affiche tout le journal de reel.py")
    args = ap.parse_args()
    if not args.tous and not args.sujet:
        ap.error("donner un sujet ou --tous")
    slugs = list(P.sujets(args.projet)) if args.tous else [args.sujet]
    codes = [un(args.projet, s, args) for s in slugs]
    sys.exit(max(codes))


if __name__ == "__main__":
    main()
