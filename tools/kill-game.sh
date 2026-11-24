#!/bin/bash
# kill-game.sh - 结束卡死的 RetroArch，回到桌面
#
# 用法：
#   ./kill-game.sh       先礼后兵：SIGTERM -> 3 秒 -> SIGKILL
#   ./kill-game.sh -f    直接 SIGKILL（确定卡死时用）
#   ./kill-game.sh -n    只列出将要结束的进程，不真的杀
#
# 说明：
#   - libretro 核心是 .so，跑在 retroarch 进程内，杀 retroarch 即可
#   - 同时清理 play-100in1.sh / start-retroarch.sh 包装进程
#   - 结束后清理屏保标记文件，必要时拉起 idle_watch.sh
set -u

export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"

MODE="term"
case "${1:-}" in
    -f|--force) MODE="kill" ;;
    -n|--dry-run) MODE="dry" ;;
    "") ;;
    *) echo "用法: $0 [-f|-n]" >&2; exit 2 ;;
esac

say() { printf '%s\n' "$*"; }

# 收集目标 PID，排除本脚本自身与父进程（避免杀掉调用它的 shell）
collect() {
    {
        pgrep -x retroarch 2>/dev/null
        pgrep -f 'play-100in1\.sh' 2>/dev/null
        pgrep -f 'start-retroarch\.sh' 2>/dev/null
    } | sort -un | while read -r p; do
        [ -n "$p" ] || continue
        [ "$p" = "$$" ] && continue
        [ "$p" = "$PPID" ] && continue
        printf '%s\n' "$p"
    done
}

TARGETS="$(collect)"
if [ -z "$TARGETS" ]; then
    say "没有运行中的 RetroArch，无需处理。"
    rm -f /tmp/wb-screensaver-active
    exit 0
fi

say "目标进程："
# shellcheck disable=SC2086
ps -o pid,stat,pcpu,etime,args -p $(echo $TARGETS | tr ' ' ',') 2>/dev/null

if [ "$MODE" = "dry" ]; then
    say "（dry-run，未执行任何操作）"
    exit 0
fi

if [ "$MODE" = "term" ]; then
    say "发送 SIGTERM ..."
    # shellcheck disable=SC2086
    kill -TERM $TARGETS 2>/dev/null
    for _ in $(seq 1 15); do
        sleep 0.2
        [ -z "$(collect)" ] && break
    done
fi

LEFT="$(collect)"
if [ -n "$LEFT" ]; then
    say "进程未响应，改用 SIGKILL ..."
    # shellcheck disable=SC2086
    kill -KILL $LEFT 2>/dev/null
    sleep 1
fi

LEFT="$(collect)"
if [ -n "$LEFT" ]; then
    say "仍有残留进程，请手动检查：$(echo $LEFT | tr '\n' ' ')"
    exit 1
fi

# 清理屏保标记，避免误判“屏保正在运行”
rm -f /tmp/wb-screensaver-active

# 守护进程不在就重新拉起，保证 60 秒后还能进屏保
if ! pgrep -f 'idle_watch\.sh' >/dev/null 2>&1; then
    say "屏保守护未运行，重新启动 ..."
    if [ -d "$HOME/wb-screensaver" ]; then
        ( cd "$HOME/wb-screensaver" && setsid bash idle_watch.sh >/dev/null 2>&1 & )
    fi
fi

# 唤醒显示，避免停在黑屏
xset dpms force on >/dev/null 2>&1 || true

say "已退出 RetroArch，回到桌面。"
say "重新启动：双击桌面「游戏模拟器」或「100合1」，或执行 ~/work/retroarch/play-100in1.sh"
