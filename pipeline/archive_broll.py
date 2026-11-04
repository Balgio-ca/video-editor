"""Convertit des rushs d'archive d'un client en copies 1080 pour s'en servir comme b-roll.

  archive_broll.py <dossier_sortie> <source> [<source> ...]

Une source est un dossier local, ou distant par SSH (« utilisateur@hôte:/chemin/vers/dossier »).
Chaque source donne un sous-dossier de <dossier_sortie> nommé d'après elle. Les originaux ne sont
pas gardés. La LUT S-Log3 est appliquée aux fichiers dont le nom commence par LUT_PREFIXE
(« C0 » par défaut, la caméra Sony), jamais aux clips de téléphone ; LUT_PREFIXE= la désactive.

Ensuite : décrire les clips dans <client>/assets/broll/index.json pour que l'édito les trouve.
"""
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plateforme import h264  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LUT = ROOT / "pipeline" / "luts" / "slog3-sgamut3-to-rec709.cube"
PREFIXE = os.environ.get("LUT_PREFIXE", "C0")
VIDEO = {".mp4", ".mov", ".m4v", ".mts"}


def slug(nom: str) -> str:
    nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-")


def rapatrier(source: str, tmp: Path) -> None:
    if re.match(r"^[^/\\]+@[^:]+:", source):
        hote, chemin = source.split(":", 1)
        p = subprocess.Popen(["ssh", "-o", "BatchMode=yes", hote, f'cd "{chemin}" && tar cf - --exclude="*RENDU*" .'],
                             stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        with tarfile.open(fileobj=p.stdout, mode="r|") as t:
            t.extractall(tmp, filter="data")
        p.wait()
    else:
        shutil.copytree(source, tmp, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*RENDU*"))


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sortie = Path(sys.argv[1])
    for source in sys.argv[2:]:
        nom = slug(Path(source.split(":", 1)[-1].rstrip("/\\")).name)
        (sortie / nom).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            rapatrier(source, Path(tmp))
            for f in sorted(Path(tmp).rglob("*")):
                if f.suffix.lower() not in VIDEO:
                    continue
                base = f.stem
                lut = bool(PREFIXE) and (base.startswith(PREFIXE) or base.startswith(f"Copie de {PREFIXE}"))
                vf = "scale='if(gt(iw,ih),1920,1080)':-2" + (f",lut3d={LUT.as_posix()}" if lut else "") + ",fps=30"
                out = sortie / nom / f"{base}.mp4"
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", f, "-vf", vf, "-an", *h264("10M"),
                                "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-color_trc", "bt709",
                                "-colorspace", "bt709", out], check=True)
                print(f"{nom}/{out.name}  LUT {'oui' if lut else 'non'}")


if __name__ == "__main__":
    main()
