#!/bin/bash
# Launch one screensaver, keep a global "active" marker, clean it up on exit.
# Usage: saver-run.sh flip|matrix|stars|random
set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
MARK="/tmp/wb-screensaver-active"
name="${1:-flip}"

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
export SDL_VIDEODRIVER=x11
# The LXDE autostart chain does not read ~/.bashrc, so set the flip-clock
# font here. Override by exporting WB_FONT before launching.
export WB_FONT="${WB_FONT:-/usr/share/fonts/truetype/dseg7-classic/dseg7-classic-latin-700-normal.ttf}"
xset s off >/dev/null 2>&1
xset -dpms >/dev/null 2>&1

# If another saver is already running, stop it so the icon always takes effect.
# The marker stores the actual Python PID, so killing it closes the window too.
if [ -f "$MARK" ]; then
    old=""
    read -r old < "$MARK" 2>/dev/null || true
    case "$old" in
        ''|*[!0-9]*) : ;;
        *)
            if kill -0 "$old" 2>/dev/null; then
                kill -9 "$old" >/dev/null 2>&1 || true
                sleep 1
            fi
            ;;
    esac
    rm -f "$MARK"
fi

case "$name" in
    flip|clock) cmd="python3 $DIR/fliqlo.py" ;;
    matrix)     cmd="python3 $DIR/matrix.py" ;;
    stars)      cmd="python3 $DIR/stars.py" ;;
    random)
        case $((RANDOM % 3)) in
            0) cmd="python3 $DIR/fliqlo.py" ;;
            1) cmd="python3 $DIR/matrix.py" ;;
            *) cmd="python3 $DIR/stars.py" ;;
        esac
        ;;
    *) echo "unknown saver: $name" >&2; exit 1 ;;
esac

trap 'rm -f "$MARK"' EXIT INT TERM

$cmd &
child=$!
printf '%s' "$child" > "$MARK"
wait "$child"
