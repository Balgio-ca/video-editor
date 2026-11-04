"""Copie allégée (720p, moins de 30 Mo) d'un rendu, pour l'envoyer sur un téléphone.

  apercu.py <reel.mp4> [<reel.mp4> ...]     écrit out/apercu/<même nom>.mp4
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
dest = ROOT / "out" / "apercu"
dest.mkdir(parents=True, exist_ok=True)
for f in map(Path, sys.argv[1:] or sys.exit(__doc__)):
    o = dest / f.name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f, "-vf", "scale=720:1280", "-c:v", "libx264", "-preset", "fast",
                    "-crf", "23", "-maxrate", "3500k", "-bufsize", "7000k", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", o], check=True)
    print(f"{o.relative_to(ROOT)} {o.stat().st_size / 1048576:.1f} Mo")
