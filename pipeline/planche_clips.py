"""Planche de contact d'un dossier de clips : une rangée par clip, une vignette toutes les N secondes, temps affiché."""
import sys, glob, subprocess, os
from PIL import Image, ImageDraw
d, pas = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
rows = []
for f in sorted(glob.glob(os.path.join(d, "*.mp4"))):
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True).stdout)
    tiles, t = [], 0.5
    while t < dur and len(tiles) < 10:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", f, "-frames:v", "1", "-vf", "scale=-2:200", "-q:v", "4", "/tmp/_pc.jpg"], check=True)
        im = Image.open("/tmp/_pc.jpg").convert("RGB"); ImageDraw.Draw(im).text((3, 3), f"{t:.0f}s", fill="yellow"); tiles.append(im); t += pas
    w = sum(x.width for x in tiles) + 220
    row = Image.new("RGB", (w, 200), (20, 20, 20)); ImageDraw.Draw(row).text((4, 90), os.path.basename(f)[:26], fill="white")
    x = 220
    for im in tiles: row.paste(im, (x, 0)); x += im.width
    rows.append(row)
W = max(r.width for r in rows); sheet = Image.new("RGB", (W, 200 * len(rows)), (20, 20, 20))
for i, r in enumerate(rows): sheet.paste(r, (0, i * 200))
out = os.path.join(d, "_planche.jpg"); sheet.save(out, quality=80); print(out)
