#!/bin/bash
# Install autostart hook and desktop launcher icons for the screensaver collection.
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
AUTOSTART="$HOME/.config/autostart"
DESKTOP="$HOME/Desktop"
mkdir -p "$AUTOSTART" "$DESKTOP" "$DIR/icons"

cat > "$AUTOSTART/wb-flipclock-screensaver.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=WB Screensaver Watcher
Comment=Start a screensaver after 60 seconds of inactivity
Exec=$DIR/start.sh
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF

make_launcher() {
    file="$1"
    label="$2"
    icon="$3"
    saver="$4"
    cat > "$DESKTOP/$file.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$label
Comment=Start screensaver now (click/touch to exit)
Exec=$DIR/saver-run.sh $saver
Icon=$DIR/icons/$icon.png
Terminal=false
EOF
    chmod +x "$DESKTOP/$file.desktop"
}

make_launcher "屏保-翻页时钟" "翻页时钟屏保" flip flip
make_launcher "屏保-天气" "天气面板屏保" weather weather
make_launcher "屏保-天气-纸质" "纸质天气面板屏保" weather-paper weather-paper
make_launcher "屏保-数字雨" "数字雨屏保" matrix matrix
make_launcher "屏保-星空" "星空屏保" stars stars
make_launcher "屏保-随机" "随机屏保" flip random

chmod +x "$DIR"/*.py "$DIR"/*.sh
echo "autostart: $AUTOSTART/wb-flipclock-screensaver.desktop"
echo "desktop icons: $DESKTOP/屏保-*.desktop"
echo "done"
