#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/src/rknn_style.c"
OUT="$HERE/librknn_style.so"

info() { printf '%s\n' "$*"; }
die()  { printf '[error] %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") [-h]

Builds librknn_style.so from src/rknn_style.c.

Modes:
  Native   on aarch64 with gcc installed (header from ./include or the SDK)
  Cross     on x86_64 with the aarch64 toolchain from the SDK

Environment:
  REPO      SDK root, used to locate librknnrt.so and the cross toolchain
  CC        override the compiler
EOF
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) die "unknown argument: $1" ;;
esac

[ -f "$SRC" ] || die "source not found: $SRC"

# --- SDK root candidates (cross compile / fallback header & lib) -------------
sdk_roots() {
    [ -n "${REPO:-}" ] && printf '%s\n' "$REPO"
    printf '%s\n' "$HERE/../repo"
    local d
    for d in "$HERE"/../RK3576* "$HOME"/quectel_work/RK3576*; do
        [ -d "$d" ] && printf '%s\n' "$d"
    done
}

# --- header ------------------------------------------------------------------
find_header() {
    local c
    for c in "$HERE/include" /usr/include/rknn /usr/local/include/rknn; do
        [ -f "$c/rknn_api.h" ] && { printf '%s\n' "$c"; return 0; }
    done
    local root
    while IFS= read -r root; do
        [ -d "$root" ] || continue
        c=$(find "$root/external/rknpu2" -path '*Linux*librknn_api/include*' \
                 -name rknn_api.h 2>/dev/null | head -1)
        [ -n "$c" ] && { dirname "$c"; return 0; }
    done < <(sdk_roots)
    return 1
}

# --- aarch64 librknnrt.so (only needed at link time) -------------------------
find_lib() {
    local c
    for c in /usr/lib/aarch64-linux-gnu/librknnrt.so \
             /usr/lib/librknnrt.so \
             /usr/local/lib/librknnrt.so; do
        [ -f "$c" ] && { dirname "$c"; return 0; }
    done
    local root
    while IFS= read -r root; do
        [ -d "$root" ] || continue
        c=$(find "$root/external/rknpu2" -path '*Linux*librknn_api/aarch64*' \
                 -name librknnrt.so 2>/dev/null | head -1)
        [ -n "$c" ] && { dirname "$c"; return 0; }
    done < <(sdk_roots)
    return 1
}

# --- cross toolchain ---------------------------------------------------------
find_cross_cc() {
    local root
    while IFS= read -r root; do
        [ -d "$root" ] || continue
        local c
        c=$(find "$root/prebuilts/gcc" -path '*aarch64*/bin/aarch64-none-linux-gnu-gcc' \
                 2>/dev/null | head -1)
        [ -x "$c" ] && { printf '%s\n' "$c"; return 0; }
    done < <(sdk_roots)
    return 1
}

INC_DIR="$(find_header)" || die "rknn_api.h not found; expected ./include/rknn_api.h"
LIB_DIR="$(find_lib || true)"

info "=== Building librknn_style.so ==="
info "  source:  $SRC"
info "  include: $INC_DIR"

TMP="$OUT.tmp.$$"
trap 'rm -f "$TMP"' EXIT

LINK=()
[ -n "$LIB_DIR" ] && LINK+=(-L"$LIB_DIR")

if [ "$(uname -m)" = "aarch64" ]; then
    CC="${CC:-$(command -v gcc || command -v cc || true)}"
    [ -n "$CC" ] || die "gcc not found; run 'apt-get install -y build-essential' or cross compile on the host"
    [ -n "$LIB_DIR" ] || die "librknnrt.so not found; install the RKNN runtime under /usr/lib"
    info "  mode:    native"
    info "  cc:      $CC ($("$CC" --version | head -1))"
    info "  lib:     $LIB_DIR"
    "$CC" -O2 -fPIC -shared -o "$TMP" "$SRC" -I"$INC_DIR" "${LINK[@]}" -lrknnrt
else
    CC="${CC:-$(find_cross_cc || true)}"
    [ -n "$CC" ] || die "aarch64 cross compiler not found; set REPO to the SDK root"
    [ -x "$CC" ] || die "cross compiler is not executable: $CC"
    [ -n "$LIB_DIR" ] || die "aarch64 librknnrt.so not found; set REPO to the SDK root"
    info "  mode:    cross compile"
    info "  cc:      $CC ($("$CC" --version | head -1))"
    info "  lib:     $LIB_DIR"
    "$CC" -O2 -fPIC -shared -o "$TMP" "$SRC" -I"$INC_DIR" "${LINK[@]}" -lrknnrt
fi

mv -f "$TMP" "$OUT"
trap - EXIT

info "  output:  $OUT ($(stat -c%s "$OUT") bytes)"
file "$OUT" | sed 's/^/  /'
