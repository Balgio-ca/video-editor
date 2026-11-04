#!/usr/bin/env python3
"""Crée work/<projet>/ et son sujets.json à partir d'un dossier de rushs ou d'une liste de fichiers.

  nouveau_projet.py <projet> --client <client> --mois AAAA-MM <dossier ou fichiers...>
      [--un-sujet-par-fichier | --un-seul-sujet NOM] [--copier | --lier]

Par défaut, un sujet par fichier vidéo (mp4, mov, mts, m4v), nommé d'après le fichier ;
--un-seul-sujet NOM met tous les rushs, en ordre alphabétique, dans un seul sujet.
Les rushs vont dans <sujet>/src/ par lien dur (--lier, défaut ; copie si le lien est impossible,
par exemple d'une carte mémoire ou d'un autre disque) ou par copie (--copier).
Les originaux ne sont jamais déplacés ni effacés. Un sujets.json existant garde ses sujets :
seuls les nouveaux sont ajoutés.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projet as P  # noqa: E402
from plateforme import WINDOWS  # noqa: E402

ROOT = P.ROOT
EXTENSIONS = {".mp4", ".mov", ".mts", ".m4v"}
VENV_PY = r".venv\Scripts\python.exe" if WINDOWS else ".venv/bin/python"
BRIEF = """\
# Brief de ce reel (facultatif) : consignes pour l'édito, en phrases simples.
# Forme suggérée, à remplacer par le vrai contenu :
# Sujet : <de quoi parle le reel>. Garder : <le passage à garder>. Ton : <le ton voulu>.
# B-roll : <les plans à montrer quand tel produit est nommé>. CTA : <l'appel à l'action>.
"""


def slug(texte: str) -> str:
    """« Promo hiver (2).MOV » sans extension -> « promo-hiver-2 »."""
    ascii_ = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "sujet"


def motif(s: str) -> str:
    """« promo-hiver » -> « Promo-Hiver »."""
    return "-".join(p[:1].upper() + p[1:] for p in s.split("-"))


def est_video(f: Path) -> bool:
    # les fichiers « ._ » sont les métadonnées que macOS laisse sur les cartes et disques exFAT
    return f.is_file() and f.suffix.lower() in EXTENSIONS and not f.name.startswith(".")


def rushs(sources: list[str]) -> list[Path]:
    trouves, vus = [], set()
    for s in sources:
        chemin = Path(s).expanduser()
        if chemin.is_dir():
            videos = [f for f in chemin.iterdir() if est_video(f)]
            if not videos:
                print(f"  aucun fichier vidéo dans {chemin} (sous-dossiers non parcourus)")
        elif chemin.is_file():
            videos = [chemin] if est_video(chemin) else []
            if not videos:
                print(f"  ignoré, pas une vidéo {'/'.join(sorted(EXTENSIONS))} : {chemin}")
        else:
            print(f"  introuvable : {chemin}")
            videos = []
        for f in videos:
            cle = f.resolve()
            if cle not in vus:
                vus.add(cle)
                trouves.append(f)
    return sorted(trouves, key=lambda f: (f.name.lower(), f.name, str(f)))


def placer(source: Path, src: Path, lier: bool) -> tuple[str, str]:
    """Met le rush dans src/ et renvoie (nom dans src/, comment) ; un nom déjà pris par un autre fichier reçoit un suffixe."""
    src.mkdir(parents=True, exist_ok=True)
    # nom en ASCII : sujets.json reste lisible partout, même lu sans UTF-8 sous Windows
    nom = unicodedata.normalize("NFKD", source.name).encode("ascii", "ignore").decode() or f"rush{source.suffix}"
    cible, n = src / nom, 2
    while cible.exists():
        try:
            a, b = cible.stat(), source.stat()
            if cible.samefile(source) or (a.st_size == b.st_size and abs(a.st_mtime - b.st_mtime) < 2):
                return cible.name, "déjà là"
        except OSError:
            pass
        cible, n = src / f"{Path(nom).stem}-{n}{source.suffix}", n + 1
    if lier:
        try:
            os.link(source, cible)
            return cible.name, "lien dur"
        except OSError:
            pass  # autre disque, carte exFAT, système sans liens durs : on copie
    shutil.copy2(source, cible)
    return cible.name, "copie" if not lier else "copie, lien dur impossible"


def main() -> int:
    ap = argparse.ArgumentParser(description="Crée un projet de reels à partir de rushs.")
    ap.add_argument("projet", help="nom du dossier dans work/")
    ap.add_argument("--client", required=True, help="profil clients/<client>.json")
    ap.add_argument("--mois", required=True, help="AAAA-MM, début du nom des fichiers finaux")
    ap.add_argument("sources", nargs="+", help="dossier de rushs ou fichiers vidéo")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--un-sujet-par-fichier", action="store_true", help="un sujet par fichier vidéo (défaut)")
    mode.add_argument("--un-seul-sujet", metavar="NOM", help="tous les rushs dans un seul sujet")
    place = ap.add_mutually_exclusive_group()
    place.add_argument("--lier", action="store_true", help="lien dur vers l'original, copie si impossible (défaut)")
    place.add_argument("--copier", action="store_true", help="copie des rushs")
    args = ap.parse_args()

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", args.mois):
        ap.error(f"--mois attend AAAA-MM (ex. 2026-11), pas « {args.mois} »")
    if not args.projet or re.search(r"[\\/]", args.projet) or args.projet.startswith((".", "_")):
        ap.error(f"nom de projet invalide : « {args.projet} » (un simple nom de dossier, sans / ni . ni _ au début)")

    fichiers = rushs(args.sources)
    if not fichiers:
        print("Aucun rush trouvé : rien n'est créé.")
        return 1

    if args.un_seul_sujet:
        s = slug(args.un_seul_sujet)
        nouveaux = {s: (motif(s), fichiers)}
    else:
        nouveaux = {}
        for f in fichiers:
            base, s, n = slug(f.stem), slug(f.stem), 2
            while s in nouveaux:
                s, n = f"{base}-{n}", n + 1
            nouveaux[s] = (motif(s), [f])

    dossier = ROOT / "work" / args.projet
    fichier_json = dossier / "sujets.json"
    data = json.loads(fichier_json.read_text(encoding="utf-8")) if fichier_json.exists() else {}
    projet = data.setdefault("_projet", {"client": args.client, "mois": args.mois})
    # un projet existant d'un autre client ou d'un autre mois : les nouveaux sujets portent les leurs
    propres = {k: v for k, v in (("client", args.client), ("mois", args.mois)) if projet.get(k) != v}

    print(f"{'Projet existant' if fichier_json.exists() else 'Nouveau projet'} : {dossier}")
    ajoutes = 0
    for s, (m, liste) in nouveaux.items():
        if s in data:
            print(f"  {s} : déjà dans sujets.json, laissé tel quel")
            continue
        src = dossier / s / "src"
        noms = []
        for f in liste:
            nom, comment = placer(f, src, lier=not args.copier)
            noms.append(nom)
            print(f"  {s}/src/{nom} ({comment})")
        brief = dossier / s / "brief.txt"
        if not brief.exists():
            brief.write_text(BRIEF, encoding="utf-8")
        data[s] = {"rushs": noms, "motif": m, **propres}
        ajoutes += 1

    if ajoutes:
        dossier.mkdir(parents=True, exist_ok=True)
        tmp = fichier_json.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(fichier_json)
    print(f"{ajoutes} sujet{'s' if ajoutes > 1 else ''} ajouté{'s' if ajoutes > 1 else ''} à {fichier_json}")
    if propres:
        print(f"  _projet garde {projet.get('client')} / {projet.get('mois')} ; "
              f"les nouveaux sujets ont leur propre client ou mois")

    profil = ROOT / "clients" / f"{args.client}.json"
    if not profil.exists():
        copie = (f"copy clients\\_template.json clients\\{args.client}.json" if WINDOWS
                 else f"cp clients/_template.json clients/{args.client}.json")
        print(f"\nProfil client absent : {profil}\n  le créer à partir du gabarit, puis l'adapter :\n  {copie}")

    if ajoutes:
        print(f"\nRemplir au besoin les brief.txt, puis lancer :\n  {VENV_PY} pipeline/rendre.py {args.projet} --tous --jusqua edito")
    return 0


if __name__ == "__main__":
    sys.exit(main())
