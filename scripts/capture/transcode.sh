#!/usr/bin/env bash
# WebM (VP8/VP9) is what page.screencast writes; Remotion wants H.264.
#
# crf 18, not 23: this is small UI text on a light background that gets scaled
# inside a Remotion frame, and compression artifacts on small type are the
# single most common way a demo video looks cheap.
#
# The .webm originals stay under captures/raw/ (gitignored) so a re-encode never
# needs a re-shoot.
#
#   scripts/capture/transcode.sh                 # every raw capture
#   scripts/capture/transcode.sh scene-06-review # just one

set -euo pipefail
cd "$(dirname "$0")/../.."

RAW=docs/demo/captures/raw
OUT=docs/demo/captures
mkdir -p "$OUT"

names=("$@")
if [ ${#names[@]} -eq 0 ]; then
  for f in "$RAW"/*.webm; do names+=("$(basename "$f" .webm)"); done
fi

for name in "${names[@]}"; do
  src="$RAW/$name.webm"
  [ -f "$src" ] || { echo "missing: $src" >&2; exit 1; }
  ffmpeg -y -loglevel warning -i "$src" \
    -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p \
    -r 30 -movflags +faststart \
    "$OUT/$name.mp4"
  printf '%-34s %s  %ss\n' "$name.mp4" \
    "$(du -h "$OUT/$name.mp4" | cut -f1)" \
    "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT/$name.mp4" | cut -c1-5)"
done
