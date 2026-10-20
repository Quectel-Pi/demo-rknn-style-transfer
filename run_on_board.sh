#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ORIGINAL_ARGS=("$@")
info()  { echo -e "\033[32m[run]\033[0m $*"; }
warn()  { echo -e "\033[33m[warn]\033[0m $*" >&2; }
die()   { echo -e "\033[31m[error]\033[0m $*" >&2; exit 1; }

MODEL=udnie
MODE=bg
PRECISION=int8
FULLSCREEN=""
CAMERA=""
FRAMES=""
POSITIONAL=0

while (($#)); do
    case "$1" in
        -m|--model)
            (($# >= 2)) || die "missing argument for $1"
            MODEL="$2"; shift 2 ;;
        --precision)
            (($# >= 2)) || die "missing argument for --precision"
            PRECISION="$2"; shift 2 ;;
        --camera)
            (($# >= 2)) || die "missing argument for --camera"
            CAMERA="$2"; shift 2 ;;
        --frames)
            (($# >= 2)) || die "missing argument for --frames"
            FRAMES="$2"; shift 2 ;;
        --fullscreen|--windowed) FULLSCREEN="$1"; shift ;;
        --fg|--foreground) MODE=fg; shift ;;
        --bg|--background) MODE=bg; shift ;;
        -h|--help)
            printf 'Usage: %s [STYLE] [--fullscreen|--windowed] [--fg] [--precision int8|fp16]\n' "$0"
            exit 0 ;;
        --*) die "unknown option: $1" ;;
        *)
            case "$1" in
                int8|fp16) PRECISION="$1" ;;
                bg|--bg) MODE=bg ;;
                *)
                    case "$POSITIONAL" in
                        0) MODEL="$1"; POSITIONAL=1 ;;
                        *) die "unrecognized positional argument: $1" ;;
                    esac
                    ;;
            esac
            shift ;;
    esac
done

case "$PRECISION" in
    int8|fp16) ;;
    *) die "precision must be int8 or fp16" ;;
esac

PY_ARGS=(-m "$MODEL" --precision "$PRECISION")
[ -n "$FULLSCREEN" ] && PY_ARGS+=("$FULLSCREEN")
[ -n "$CAMERA" ] && PY_ARGS+=(--camera "$CAMERA")
[ -n "$FRAMES" ] && PY_ARGS+=(--frames "$FRAMES")

if [ "$(id -u)" -eq 0 ]; then
    DESKTOP_USER="${DEMO_USER:-q}"
    DESKTOP_UID="$(id -u "$DESKTOP_USER" 2>/dev/null)" \
        || die "desktop user $DESKTOP_USER not found; set DEMO_USER to override"
    DESKTOP_RUNTIME="${DEMO_XDG_RUNTIME_DIR:-/run/user/$DESKTOP_UID}"
    DESKTOP_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
    case "$DESKTOP_DISPLAY" in
        /*) WAYLAND_SOCKET="$DESKTOP_DISPLAY" ;;
        *) WAYLAND_SOCKET="$DESKTOP_RUNTIME/$DESKTOP_DISPLAY" ;;
    esac
    [ -S "$WAYLAND_SOCKET" ] \
        || die "Wayland socket not found: $WAYLAND_SOCKET; make sure $DESKTOP_USER is logged in"
    command -v runuser >/dev/null 2>&1 || die "runuser not found; cannot switch to desktop user $DESKTOP_USER"
    pkill -f '[o]il_painting_cam.py' 2>/dev/null || true
    pkill -f '[g]st-launch.*video33' 2>/dev/null || true
    sleep 1
    info "running as root, switching to desktop user $DESKTOP_USER to reach Wayland"
    exec runuser -u "$DESKTOP_USER" -- env \
        GST_V4L2_FORCE_LIBV4L2=0 \
        WAYLAND_DISPLAY="$DESKTOP_DISPLAY" \
        XDG_RUNTIME_DIR="$DESKTOP_RUNTIME" \
        LD_LIBRARY_PATH="/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        "$HERE/run_on_board.sh" "${ORIGINAL_ARGS[@]}"
fi

export GST_V4L2_FORCE_LIBV4L2=0
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export LD_LIBRARY_PATH="/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

info "cleaning up old processes..."
pkill -f '[o]il_painting_cam.py' 2>/dev/null || true
pkill -f '[g]st-launch.*video33' 2>/dev/null || true
sleep 1

[ -f "$HERE/oil_painting_cam.py" ] && [ -f "$HERE/librknn_style.so" ] \
    || die "missing demo files (oil_painting_cam.py / librknn_style.so)"

if [ "$MODE" = "fg" ]; then
    info "foreground start (Ctrl+C to quit): $MODEL, $PRECISION, ${FULLSCREEN:---windowed}"
    cd "$HERE"
    exec python3 -u oil_painting_cam.py "${PY_ARGS[@]}"
else
    info "background start: $MODEL, $PRECISION, ${FULLSCREEN:---windowed} (log: /tmp/demo_run.log)"
    cd "$HERE"
    nohup python3 -u oil_painting_cam.py "${PY_ARGS[@]}" \
        > /tmp/demo_run.log 2>&1 < /dev/null &
    PID=$!
    printf '%s\n' "$PID" > /tmp/m2_demo_youhua.pid
    sleep 4
    if kill -0 "$PID" 2>/dev/null; then
        info "started, PID=$PID"
        info "log:  tail -f /tmp/demo_run.log"
        info "stop: ./stop_on_board.sh"
    else
        warn "process not running, log tail:"
        tail -10 /tmp/demo_run.log
        die "failed to start"
    fi
fi
