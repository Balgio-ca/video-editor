"""Compte les b-roll utilisés dans tous les reels d'un projet (edit.json) : un clip Pexels ne devrait servir
qu'une fois dans une série, un clip du client trois fois au plus. Usage : broll_usage.py <projet>"""
import json, glob, collections, sys
use = collections.defaultdict(list)
for f in sorted(glob.glob(f"work/{sys.argv[1]}/*/edit.json")):
    slug = f.split("/")[2]
    for b in json.load(open(f)).get("broll", []):
        use[b["source"]].append(slug)
for src, slugs in sorted(use.items(), key=lambda x: -len(x[1])):
    if len(slugs) > 1 or src.startswith("pexels"):
        print(f"{len(slugs):2d}  {src:45s} {', '.join(slugs)}")
