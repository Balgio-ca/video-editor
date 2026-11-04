"""Écoute un passage du rush d'un sujet : enveloppe sonore et mots horodatés, pour placer une coupe.

  ecouter.py <projet> <sujet> <début_s> <fin_s> [--pas 0.03]

Les temps sont ceux du rush coupé (rush_cut.mp4, celui de words.json). L'enveloppe est le niveau
relatif au pic du sujet (0 = silence, 1 = le plus fort) : une voix est au-dessus de 0,3, un souffle
ou un murmure vers 0,1, le silence sous 0,05. On coupe dans un creux, juste avant l'attaque du mot.

Exemple : un « euh » avant la question, entre 545,5 et 546,4 s :
  ecouter.py mon-projet faq-7 545.4 546.5
  545.52:0.20 545.58:0.68 ... 546.10:0.13 546.16:0.28 546.22:0.54
  mots : (546.14 Le) (546.40 plancher) ...
puis dans edit.json : {"debut_mot": 0, "fin_mot": 1756, "debut_s": 0.0, "fin_s": 546.11}
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import projet as P  # noqa: E402
from plateforme import transcrire  # noqa: E402
from reel import load_envelope  # noqa: E402

if len(sys.argv) < 5 or sys.argv[1] in ("-h", "--help"):
    print(__doc__)
    sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 1)
projet, slug, t0, t1 = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
pas = float(sys.argv[sys.argv.index("--pas") + 1]) if "--pas" in sys.argv else 0.03
w = P.dossier(projet) / slug
wav = w / "audio16k.wav"
if not wav.exists():
    sys.exit(f"{wav} manque : lancer d'abord la transcription (rendre.py {projet} {slug} --jusqua transcribe)")
env, hop = load_envelope(wav)
pic = float(env.max()) or 1.0
a = int(t0 / hop)
print(" ".join(f"{t0 + i * hop:.2f}:{env[a + i] / pic:.2f}" for i in range(0, int((t1 - t0) / hop), max(1, int(pas / hop)))))

words = json.loads((w / "words.json").read_text())["words"] if (w / "words.json").exists() else []
dans = [x for x in words if x["end"] > t0 and x["start"] < t1]
print("words.json :", " ".join(f"({x['i']}:{x['start']:.2f} {x['text']})" for x in dans))

langue = P.sujet(projet, slug)["langue"]
with tempfile.TemporaryDirectory() as tmp:
    part = f"{tmp}/passage.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", wav, part], check=True)
    r = transcrire(part, langue)
print("réécoute  :", " ".join(f"({t0 + m['start']:.2f} {m['word'].strip()})" for s in r["segments"] for m in s["words"]))
