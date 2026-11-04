#!/bin/bash
# Copie allégée (< 30 Mo) d'un rendu pour l'envoi sur téléphone : apercu.sh <fichier.mp4>
set -e
cd "$(dirname "$0")/.."
mkdir -p out/apercu
f="$1"; o="out/apercu/$(basename "$f")"
ffmpeg -v error -y -i "$f" -vf "scale=720:1280" -c:v libx264 -preset fast -crf 23 -maxrate 3500k -bufsize 7000k -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart "$o"
ls -la "$o" | awk '{printf "%s %.1f Mo\n", $NF, $5/1048576}'
