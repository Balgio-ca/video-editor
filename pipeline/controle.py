"""Contrôle d'un rendu : durée, LUFS, et une planche (accroche, milieu de chaque b-roll, chute, carte de fin).

  controle.py <projet> <sujet> [--ecoute [langue]]

--ecoute retranscrit la piste parlée montée, pour attraper une coupe qui mange un mot.
La planche est écrite dans work/<projet>/check_<sujet>.jpg.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projet as P  # noqa: E402

projet, slug = sys.argv[1], sys.argv[2]
s = P.sujet(projet, slug)
f = P.rendu(s)
if not f:
    sys.exit(f"aucun rendu out/{s['client']}/{s['mois']}_{s['motif']}*.mp4")
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True).stdout)
ln = subprocess.run(["ffmpeg", "-hide_banner", "-i", f, "-af", "loudnorm=print_format=summary", "-f", "null", "-"], capture_output=True, text=True).stderr
lufs = re.search(r"Input Integrated:\s+(-?[0-9.]+)", ln).group(1)
html = (s["work"] / "comp" / "index.html").read_text()
clips = re.findall(r'id="broll(\d+)"[^>]*data-start="([0-9.]+)"[^>]*data-duration="([0-9.]+)"', html)
hook = re.search(r'id="hook"[^>]*data-duration="([0-9.]+)"', html)
print(f"{f.relative_to(P.ROOT)} : {dur:.1f} s, {lufs} LUFS, accroche {hook.group(1) if hook else '-'} s, {len(clips)} b-roll")
times = [0.8] + [float(st) + float(du) / 2 for _, st, du in clips] + [dur - 4.2, dur - 0.5]
tiles = []
with tempfile.TemporaryDirectory() as tmp:
    for t in times:
        jpg = f"{tmp}/f.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", f, "-frames:v", "1", "-vf", "scale=200:-1", "-q:v", "3", jpg], check=True)
        im = Image.open(jpg).convert("RGB")
        ImageDraw.Draw(im).text((4, 4), f"{t:.1f}s", fill="yellow")
        tiles.append(im)
    sheet = Image.new("RGB", (200 * len(tiles), tiles[0].height))
    for i, im in enumerate(tiles):
        sheet.paste(im, (i * 200, 0))
    out = P.dossier(projet) / f"check_{slug}.jpg"
    sheet.save(out, quality=85)
    print(out.relative_to(P.ROOT))
    if "--ecoute" in sys.argv:
        from plateforme import transcrire

        i = sys.argv.index("--ecoute")
        langue = sys.argv[i + 1] if len(sys.argv) > i + 1 else s["langue"]
        wav = f"{tmp}/ecoute.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", s["work"] / "talk.mp4", "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
        r = transcrire(wav, langue, mots=False)
        print("ÉCOUTE :", r["text"].strip())
