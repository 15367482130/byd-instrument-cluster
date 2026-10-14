#!/system/bin/sh
# ------------------------------------------------------------
# Magisk / KernelSU 模块 · 开机自动开启仪表飞屏
#
# 注意：这个脚本必须**立刻返回**，否则会拖住开机流程。
# 真正的逻辑丢到后台子进程里，等 sys.boot_completed 再执行。
# ------------------------------------------------------------

MODDIR=${0%/*}
CONF=/data/adb/byd-feipin.conf
LOG=/data/adb/byd-feipin.log

# ---------- 首次运行生成默认配置 ----------
if [ ! -f "$CONF" ]; then
    cat >"$CONF" <<'EOF'
# BYD 仪表飞屏 · 开机自动配置
# 改完保存即可，下次开机生效；想立刻生效见 root/README.md

# 1 = 开机自动执行   0 = 不执行
ENABLE=1

# 1 = 常驻守护，发现仪表不是「全屏导航」就自动重开
# 0 = 只在开机时执行一次
LOOP=0

# 守护巡检间隔（秒），仅 LOOP=1 时有效
INTERVAL=60
EOF
    chmod 644 "$CONF" 2>/dev/null
fi

# shellcheck disable=SC1090
. "$CONF" 2>/dev/null

[ "$ENABLE" = "1" ] || exit 0

S="$MODDIR/byd-feipin.sh"
[ -f "$S" ] || exit 0
chmod 755 "$S" 2>/dev/null

# ---------- 丢到后台，不阻塞开机 ----------
(
    echo "[$(date '+%m-%d %H:%M:%S')] service.sh: 等待系统启动完成…" >>"$LOG" 2>/dev/null

    n=0
    while [ "$(getprop sys.boot_completed)" != "1" ] && [ "$n" -lt 150 ]; do
        sleep 2
        n=$((n + 1))
    done

    # 再多等一会儿，让车机的仪表服务就绪
    sleep 12

    if [ "$LOOP" = "1" ]; then
        BYD_INTERVAL="$INTERVAL"
        export BYD_INTERVAL
        exec sh "$S" watchdog
    else
        exec sh "$S" on
    fi
) >/dev/null 2>&1 &
