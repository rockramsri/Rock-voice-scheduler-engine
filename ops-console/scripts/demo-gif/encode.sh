#!/usr/bin/env bash
# webm -> README hero GIF. Reads raw/meta.json written by record.mjs.
# Usage: bash scripts/demo-gif/encode.sh   (from ops-console/)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
META="$HERE/raw/meta.json"
VIDEO="$(python3 -c "import json;print(json.load(open('$META'))['video'])")"
START="$(python3 -c "import json;print(json.load(open('$META'))['startOffsetSec'])")"
DUR="$(python3 -c "import json;print(json.load(open('$META'))['durationSec'])")"
OUT="$HERE/../../../docs/assets/hero-console.gif"
mkdir -p "$(dirname "$OUT")"

encode () { # $1=width $2=fps $3=colors
  ffmpeg -y -loglevel error -ss "$START" -t "$DUR" -i "$VIDEO" -filter_complex \
    "[0:v] fps=$2,scale=$1:-1:flags=lanczos,split [a][b]; \
     [a] palettegen=max_colors=$3:stats_mode=diff [p]; \
     [b][p] paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" \
    "$OUT"
}

shrink () { command -v gifsicle >/dev/null && gifsicle -O3 --lossy=90 -b "$OUT" || true; }

encode 1080 14 96; shrink
SIZE=$(stat -f%z "$OUT")
if [ "$SIZE" -gt 5000000 ]; then encode 960 12 72; shrink; SIZE=$(stat -f%z "$OUT"); fi
if [ "$SIZE" -gt 5000000 ]; then encode 840 10 48; shrink; SIZE=$(stat -f%z "$OUT"); fi
echo "hero gif: $OUT ($((SIZE / 1024)) KB)"
