#!/bin/bash
# Single-instance launcher used by LXDE autostart.
DIR="$(cd "$(dirname "$0")" && pwd)"
exec flock -n /tmp/wb-screensaver.lock bash "$DIR/idle_watch.sh"
