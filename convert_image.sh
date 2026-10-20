#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

info() { printf '[img] %s\n' "$*"; }
die()  { printf '[error] %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") INPUT... [-o PATH | -d DIR] [-m MODEL] [OPTIONS]

Runs the RKNN style transfer on images and writes new image files.

Output options:
  -o, --output PATH   output file, or a directory (use a trailing /) to put
                      generated names in; {stem} and {model} are substituted
  -d, --outdir DIR    write into DIR using generated names
                      default: <input dir>/<input>_<model>.<ext>

Other options:
  -m, --model NAME    style name (default: udnie)
      --precision P   int8 or fp16 (default: int8)
      --keep-size     keep the model output size instead of scaling back
      --interp NAME   rescale interpolation: nearest, linear, cubic, lanczos
  -q, --quiet         only print errors

Examples:
  ./convert_image.sh cat.png
  ./convert_image.sh cat.png -o cat_painting.jpg
  ./convert_image.sh cat.png -o out/
  ./convert_image.sh cat.png -d out/paintings
  ./convert_image.sh a.png b.png -o out/ -m udnie
  ./convert_image.sh cat.png -o 'out/{stem}_{model}.png'
EOF
}

[ $# -ge 1 ] || { usage >&2; exit 1; }
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
esac

[ -f "$HERE/image_style.py" ] || die "image_style.py is missing next to this script"
[ -f "$HERE/librknn_style.so" ] || die "librknn_style.so is missing; run ./build.sh"
[ -f "$HERE/models/rknn/udnie-9_int8_rk3576.rknn" ] \
    || info "[warn] default model not found under models/rknn"

command -v python3 >/dev/null 2>&1 || die "python3 not found"
python3 -c 'import numpy, cv2' 2>/dev/null \
    || die "python3 numpy/cv2 not available"

info "input: $1"
exec python3 -u "$HERE/image_style.py" "$@"
