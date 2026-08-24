#!/usr/bin/env bash
# webm -> evals README GIF. Reads raw/meta-evals.json written by
# record-evals.mjs and speed-cuts the milestone marks into ~30s:
# real footage only, minutes of run time compressed per segment.
# Usage: bash scripts/demo-gif/encode-evals.sh   (from ops-console/)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
META="$HERE/raw/meta-evals.json"
OUT="$HERE/../../../docs/assets/eval-lab.gif"
mkdir -p "$(dirname "$OUT")"

VIDEO="$(python3 -c "import json;print(json.load(open('$META'))['video'])")"

# Each row: start_mark offset_s duration_s speed
# (duration is capped to the next mark so cuts never overlap dead air).
FILTER="$(python3 - "$META" <<'PY'
import json, sys
meta = json.load(open(sys.argv[1]))
m = meta["marks"]
plan = [
    ("wide",    0.0, 4.4, 1.0),    # reference grid + merge headline zoom
    ("click",  -0.3, 3.6, 1.0),    # pressing check regression
    ("pytest",  0.5, 6.0, 3.0),    # L1 pytest console streaming
    ("l2",      0.0, 4.5, 3.0),    # L2 component stage
    ("turns",  -0.5, 9.0, 1.9),    # live persona <-> agent bubbles
    ("tool",   -1.5, 4.5, 1.9),    # accept_this_shift chip
    ("verdict",-1.0, 4.0, 1.4),    # CONFIRMED_CORRECT + judge yes
    ("browse",  0.0, 999, 1.8),    # decks fan out, transcripts + judge quotes
]
segs = []
for name, off, dur, speed in plan:
    if name not in m:
        continue
    start = max(0.0, m[name] + off)
    end = start + dur
    if name == "browse" and "end" in m:
        end = m["end"] + 1.2
    segs.append((start, max(0.5, end - start), speed))
parts, concat = [], ""
for i, (start, dur, speed) in enumerate(segs):
    parts.append(
        f"[0:v] trim=start={start:.2f}:duration={dur:.2f},"
        f"setpts=(PTS-STARTPTS)/{speed} [s{i}];")
    concat += f"[s{i}]"
print("".join(parts) + f"{concat}concat=n={len(segs)}:v=1:a=0 [cut]")
PY
)"

encode () { # $1=width $2=fps $3=colors
  ffmpeg -y -loglevel error -i "$VIDEO" -filter_complex \
    "$FILTER; [cut] fps=$2,scale=$1:-1:flags=lanczos,split [a][b]; \
     [a] palettegen=max_colors=$3:stats_mode=diff [p]; \
     [b][p] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
    "$OUT"
}

# denser UI than the hero gif (dot grids, tables) — lean harder on lossy
shrink () { command -v gifsicle >/dev/null && gifsicle -O3 --lossy=130 -b "$OUT" || true; }

encode 1080 14 96; shrink
SIZE=$(stat -f%z "$OUT")
if [ "$SIZE" -gt 5000000 ]; then encode 960 12 72; shrink; SIZE=$(stat -f%z "$OUT"); fi
if [ "$SIZE" -gt 5000000 ]; then encode 840 10 48; shrink; SIZE=$(stat -f%z "$OUT"); fi
if [ "$SIZE" -gt 5000000 ]; then encode 760 9 48; shrink; SIZE=$(stat -f%z "$OUT"); fi
echo "eval lab gif: $OUT ($((SIZE / 1024)) KB)"
