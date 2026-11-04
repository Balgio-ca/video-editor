#!/bin/bash
# Rapatrie des rushs d'archive d'un client en copies de travail 1080 pour s'en servir comme b-roll,
# sans garder les originaux en local.
#
#   archive_broll.sh <dossier_sortie> <source> [<source> ...]
#
# Une source est un dossier local ou distant par SSH (« utilisateur@hôte:/chemin/vers/dossier »).
# Chaque source donne un sous-dossier de <dossier_sortie>, nommé d'après le dossier source.
# La LUT S-Log3 est appliquée aux fichiers dont le nom correspond à LUT_MOTIF (C0* par défaut, la
# caméra Sony), jamais aux clips de téléphone. LUT_MOTIF= (vide) désactive la LUT.
# Ensuite : indexer les clips dans <client>/assets/broll/index.json pour que le pipeline les trouve.
cd "$(dirname "$0")/.."
OUT="$1"; shift
[ -z "$OUT" ] || [ $# -eq 0 ] && { sed -n '2,12p' "$0"; exit 1; }
LUT_MOTIF="${LUT_MOTIF-C0*}"
for src in "$@"; do
  slug=$(basename "${src#*:}" | iconv -f utf-8 -t ascii//TRANSLIT 2>/dev/null | tr -cs 'A-Za-z0-9' '-' | sed 's/^-//;s/-$//' | tr 'A-Z' 'a-z')
  mkdir -p "$OUT/$slug" "$OUT/_tmp"
  case "$src" in
    *@*:*) ssh -n -o BatchMode=yes "${src%%:*}" "cd \"${src#*:}\" && tar cf - --exclude='*RENDU*' ." | tar xf - -C "$OUT/_tmp" ;;
    *) (cd "$src" && tar cf - --exclude='*RENDU*' .) | tar xf - -C "$OUT/_tmp" ;;
  esac
  find "$OUT/_tmp" -type f \( -iname '*.mp4' -o -iname '*.mov' \) | while IFS= read -r f; do
    b=$(basename "$f"); b="${b%.*}"
    lut=""
    if [ -n "$LUT_MOTIF" ]; then
      case "$b" in $LUT_MOTIF|"Copie de "$LUT_MOTIF) lut=",lut3d=pipeline/luts/slog3-sgamut3-to-rec709.cube";; esac
    fi
    ffmpeg -nostdin -v error -y -i "$f" -vf "scale='if(gt(iw,ih),1920,1080)':-2${lut},fps=30" -an -c:v h264_videotoolbox -b:v 10M -pix_fmt yuv420p -color_primaries bt709 -color_trc bt709 -colorspace bt709 "$OUT/$slug/$b.mp4" < /dev/null
    echo "$slug/$b.mp4 lut=${lut:+oui} $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$slug/$b.mp4" < /dev/null)s"
    rm -f "$f"
  done
  rm -rf "$OUT/_tmp"
done
