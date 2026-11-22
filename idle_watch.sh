#!/bin/bash
# Poll X11 idle time; launch a screensaver after 60 s of inactivity.
# The screensaver manages its own lifetime (click/touch exits); this loop only starts it.

set -u

DIR="$(cd "$(dirname "$0")" && pwd)"
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
IDLE_MS="${WB_IDLE_MS:-60000}"
LOG="$DIR/idle_watch.log"
MARK="/tmp/wb-screensaver-active"

log() {
    printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"
}

# A marker file records the PID of a running saver (including manually launched ones).
saver_running() {
    [ -f "$MARK" ] || return 1
    local pid=""
    read -r pid < "$MARK" 2>/dev/null || true
    case "$pid" in
        ''|*[!0-9]*) rm -f "$MARK"; return 1 ;;
    esac
    if kill -0 "$pid" 2>/dev/null; then
        return 0
    fi
    rm -f "$MARK"
    return 1
}

# X's own blanking/DPMS would turn the panel off; let our saver own the screen.
xset s off >/dev/null 2>&1
xset s noblank >/dev/null 2>&1
xset -dpms >/dev/null 2>&1

log "watcher started: display=$DISPLAY threshold=${IDLE_MS}ms"

while true; do
    if saver_running; then
        sleep 2
        continue
    fi

    idle="$(xprintidle 2>/dev/null || echo 0)"
    case "$idle" in
        ''|*[!0-9]*) idle=0 ;;
    esac

    if [ "$idle" -ge "$IDLE_MS" ]; then
        saver="${WB_IDLE_SAVER:-flip}"
        log "idle=${idle}ms -> start $saver"
        nohup "$DIR/saver-run.sh" "$saver" >> "$LOG" 2>&1 &
    fi
    sleep 2
done
