"""Planche de candidats Pexels (vidéos portrait) pour choisir un b-roll à l'œil.
Usage : pexels_candidats.py <dossier_sortie> "tag=requête" ["tag=requête" ...]
Écrit <dossier>/_candidats.jpg (une rangée par requête, id et durée sur chaque vignette)."""
import os, sys, pathlib, requests
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import plateforme  # noqa: E402,F401  (charge .env)
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
key = os.environ["PEXELS_API_KEY"]
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
font = ImageFont.truetype(str(ROOT / "templates/balgio-reel/fonts/Montserrat.ttf"), 18)
sheets = []
for arg in sys.argv[2:]:
    tag, q = arg.split("=", 1)
    r = requests.get("https://api.pexels.com/videos/search", params={"query": q, "orientation": "portrait", "size": "medium", "per_page": 12},
                     headers={"Authorization": key}, timeout=30).json()
    tiles = []
    for v in r.get("videos", []):
        if v.get("duration", 0) < 3 or len(tiles) >= 8:
            continue
        f = out / f"{tag}_{v['id']}.jpg"
        if not f.exists():
            f.write_bytes(requests.get(v["image"], timeout=30).content)
        im = Image.open(f).convert("RGB"); w, h = im.size
        s = max(200 / w, 356 / h); im = im.resize((int(w * s) + 1, int(h * s) + 1))
        l, t = (im.width - 200) // 2, (im.height - 356) // 2
        im = im.crop((l, t, l + 200, t + 356))
        d = ImageDraw.Draw(im); d.rectangle((0, 0, 200, 24), fill=(0, 0, 0)); d.text((4, 3), f"{v['id']} {v['duration']}s", fill="white", font=font)
        tiles.append(im)
    sheet = Image.new("RGB", (1600, 382), (20, 20, 20))
    ImageDraw.Draw(sheet).text((4, 4), f"{tag} : {q}", fill="white", font=font)
    for i, im in enumerate(tiles):
        sheet.paste(im, (i * 200, 26))
    sheets.append(sheet); print(tag, len(tiles), "candidats")
big = Image.new("RGB", (1600, 382 * len(sheets)), (20, 20, 20))
for i, s in enumerate(sheets):
    big.paste(s, (0, i * 382))
big.save(out / "_candidats.jpg", quality=85); print(out / "_candidats.jpg")
