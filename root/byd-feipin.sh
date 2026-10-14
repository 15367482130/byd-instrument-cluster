#!/system/bin/sh
# ============================================================
# BYD 仪表飞屏 · root 版
#
# 与 ADB 版的区别：不需要开「无线 ADB 调试」、不需要 5555 端口、
# 不需要授权弹窗，重启也不会失效。直接以 root(uid 0) 身份调用
# 车机自带的 Binder 服务。
#
#   sh byd-feipin.sh on        开启全屏导航（飞屏）
#   sh byd-feipin.sh off       关闭
#   sh byd-feipin.sh small     切小屏导航
#   sh byd-feipin.sh status    只读当前仪表导航类型
#   sh byd-feipin.sh diag      环境自检（会验证 root 身份能不能调服务）
#   sh byd-feipin.sh raw <命令> 直接执行一条命令（调试用）
#   sh byd-feipin.sh watchdog  守护循环（一般由开机脚本调用）
#
# 所有命令都来自公开逆向资料，与 PC 版 / 车机 App 版完全一致。
# 只调用车机自带接口，不刷机、不改固件、不写系统分区。
# ============================================================

export PATH=/system/bin:/system/xbin:/system/sbin:/sbin:/vendor/bin:$PATH

# ---------- 常量（不同固件可能有差异，可用 raw 子命令试） ----------
DEV=1007                     # INSTRUMENT_DEVICE_ID
F_READ=1086337074            # 读 INSTRUMENT_NAVI_TYPE
F_SET=1276157976             # 写 INSTRUMENT_NAVI_TYPE_SET
T_READ=5
T_SET=6
CLUSTER_PKG=com.byd.clusterdebug

MODE_SIMPLE=39               # 简易导航（转向卡片）
MODE_FULL=16                 # 全屏投影
MODE_HALF=17                 # 半屏投影
MODE_OFF=18                  # 关闭投影
MODE_DI4=35                  # Di4.0 模式：创建投影显示

NAVI_NAME_1="关闭"
NAVI_NAME_2="随导航"
NAVI_NAME_3="小屏导航"
NAVI_NAME_4="全屏导航"

# ---------- 日志 ----------
if [ -d /data/adb ]; then
    LOG=/data/adb/byd-feipin.log
else
    LOG=/data/local/tmp/byd-feipin.log
fi

TS() { date '+%m-%d %H:%M:%S'; }

say() {
    echo "[$(TS)] $*"
    echo "[$(TS)] $*" >>"$LOG" 2>/dev/null
}

# ---------- root 检查：不是 root 就自己 su 一遍 ----------
ensure_root() {
    [ "$(id -u)" = "0" ] && return 0
    if command -v su >/dev/null 2>&1; then
        say "当前非 root，尝试通过 su 重新执行…"
        exec su -c "sh $SELF $*"
    fi
    echo "!! 需要 root 权限，且找不到 su。先在车机上取得 root 再运行。" >&2
    exit 1
}

# ---------- 三个原始接口 ----------
svc_read()  { service call autoservice $T_READ i32 $DEV i32 $F_READ; }
svc_set()   { service call autoservice $T_SET  i32 $DEV i32 $F_SET i32 "$1"; }
proj()      { service call AutoContainer 2 i32 1000 s16 "$1"; }

is_denied() {
    echo "$1" | grep -qiE 'exception|permission denial|security exception|not found|no such|cannot find|unable to'
}

# 从 "Result: Parcel(00000000 00000004 '....')" 里取出最后一个 8 位十六进制数
navi_type() {
    raw=$(svc_read 2>&1)
    hex=$(printf '%s' "$raw" | sed "s/'[^']*'//g" \
          | grep -o '[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]' \
          | tail -n 1)
    [ -z "$hex" ] && return 1
    echo $((0x$hex))
}

navi_name() {
    case "$1" in
        1) echo "$NAVI_NAME_1" ;;
        2) echo "$NAVI_NAME_2" ;;
        3) echo "$NAVI_NAME_3" ;;
        4) echo "$NAVI_NAME_4" ;;
        *) echo "未知" ;;
    esac
}

# ---------- 找定制版地图包 ----------
detect_map() {
    list=$(pm list packages 2>/dev/null | sed -n 's/^package://p')
    for pat in autonavi.minimap.byd byd.amap byd.autonavi autonavi amap baidu bmap tencent; do
        hit=$(printf '%s\n' "$list" | grep -i -- "$pat" | head -n 1)
        if [ -n "$hit" ]; then echo "$hit"; return 0; fi
    done
    return 1
}

# ---------- 开启序列 ----------
do_open() {
    say "== 开启仪表全屏导航（飞屏）=="

    say "① 启动仪表调试代理 ClusterDebug"
    am startservice -n $CLUSTER_PKG/.ClusterDebugService >/dev/null 2>&1 \
        || say "   !! 启动服务失败（可能没有该组件）"
    sleep 0.4
    am start -n $CLUSTER_PKG/.MainActivity >/dev/null 2>&1 \
        || say "   !! 打开调试界面失败（不影响后续）"
    sleep 0.6

    say "② 仪表导航类型 → 4（全屏导航）"
    out=$(svc_set 4 2>&1)
    if is_denied "$out"; then
        say "   !! 写入被拒绝：$out"
        say "   → 说明 root 身份调不通该服务，看 README「兜底方案」"
    else
        say "   OK"
    fi
    sleep 0.4

    say "③ 触发投影：35 创建 Di4.0 显示 → 16 全屏"
    proj $MODE_DI4 >/dev/null 2>&1
    sleep 1
    proj $MODE_FULL >/dev/null 2>&1
    sleep 0.6

    say "④ 拉起定制版地图（触发仪表出图）"
    pkg=$(detect_map)
    if [ -n "$pkg" ]; then
        monkey -p "$pkg" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
        say "   已拉起：$pkg"
    else
        say "   未找到定制版地图包，请在车机上手动打开导航"
    fi

    t=$(navi_type)
    if [ -n "$t" ]; then
        say "⑤ 回读：导航类型 = $t（$(navi_name "$t")）"
    else
        say "⑤ 回读失败（读接口可能不支持）"
    fi

    say "完成。若仪表没出图：确认方向盘右侧菜单已选「全屏导航」；确认地图是定制版。"
}

# ---------- 关闭 ----------
do_close() {
    say "== 关闭投影 =="
    proj $MODE_OFF >/dev/null 2>&1
    sleep 0.3
    svc_set 1 >/dev/null 2>&1
    sleep 0.3
    t=$(navi_type)
    [ -n "$t" ] && say "回读：导航类型 = $t（$(navi_name "$t")）"
}

# ---------- 小屏 ----------
do_small() {
    say "== 切换小屏导航 =="
    svc_set 3 >/dev/null 2>&1
    sleep 0.4
    proj $MODE_HALF >/dev/null 2>&1
    sleep 0.3
    t=$(navi_type)
    [ -n "$t" ] && say "回读：导航类型 = $t（$(navi_name "$t")）"
}

# ---------- 只读状态 ----------
do_status() {
    raw=$(svc_read 2>&1)
    echo "$raw"
    t=$(navi_type)
    if [ -n "$t" ]; then
        echo "→ 仪表导航类型 = $t（$(navi_name "$t")）"
    else
        echo "→ 解析失败，原始输出见上"
    fi
}

# ---------- 环境自检 ----------
do_diag() {
    echo "===== BYD 飞屏 · root 版自检 ====="
    echo "时间        : $(date)"
    echo "uid         : $(id)" 
    echo "SELinux     : $(getenforce 2>/dev/null || echo 未知)"
    echo "Android     : $(getprop ro.build.version.release)"
    echo "机型/产品   : $(getprop ro.product.model)"
    echo "固件版本    : $(getprop ro.build.display.id)"
    echo ""

    echo "--- 关键工具 ---"
    for c in service am pm monkey su; do
        p=$(command -v "$c" 2>/dev/null)
        if [ -n "$p" ]; then echo "  [OK ] $c -> $p"; else echo "  [!! ] $c 不存在"; fi
    done
    echo ""

    echo "--- ClusterDebug 是否安装 ---"
    if pm list packages 2>/dev/null | grep -q "$CLUSTER_PKG"; then
        echo "  [OK ] $CLUSTER_PKG"
    else
        echo "  [!! ] 未发现 $CLUSTER_PKG（固件不同？）"
    fi
    echo ""

    echo "--- 相关 Binder 服务 ---"
    service list 2>/dev/null | grep -iE 'autoservice|AutoContainer' || echo "  !! 未找到 autoservice / AutoContainer"
    echo ""

    echo "--- 控制器属性（找 18.x / 21.x）---"
    getprop 2>/dev/null | grep -iE 'ivi|controller|cluster|byd' | head -20
    echo ""

    echo "--- 实测：以 root 身份读仪表导航类型 ---"
    echo "  \$ service call autoservice $T_READ i32 $DEV i32 $F_READ"
    raw=$(svc_read 2>&1)
    echo "$raw" | sed 's/^/    /'
    t=$(navi_type)
    if [ -n "$t" ]; then
        echo "  → 解析成功，当前导航类型 = $t（$(navi_name "$t")）"
        echo "  → root 身份可调用该服务，直接跑 on 即可"
    elif is_denied "$raw"; then
        echo "  !! 被拒绝 —— root 身份调不通，见 README「兜底方案」"
    else
        echo "  ?? 输出无法解析，把上面的原始输出发出来看"
    fi
    echo ""

    echo "--- 已装地图包 ---"
    pm list packages 2>/dev/null | grep -iE 'autonavi|amap|baidu|bmap|tencent' || echo "  （无）"
    echo ""
    echo "日志文件：$LOG"
}

# ---------- 守护：发现不是全屏就重开 ----------
INTERVAL=${BYD_INTERVAL:-60}

do_watchdog() {
    say "守护启动，间隔 ${INTERVAL}s"
    while :; do
        t=$(navi_type)
        if [ "$t" = "4" ]; then
            sleep "$INTERVAL"
            continue
        fi
        if [ -z "$t" ]; then
            say "读不到导航类型（可能服务未就绪），稍后重试"
            sleep 30
            continue
        fi
        say "检测到导航类型 = $t，不是全屏（4），自动重开"
        do_open
        sleep "$INTERVAL"
    done
}

# ---------- 入口 ----------
SELF="$0"
case "$SELF" in
    /*) ;;
    *) SELF="$(pwd)/$SELF" ;;
esac

cmd=$1
shift 2>/dev/null

case "$cmd" in
    on|open)      ensure_root "$@"; do_open ;;
    off|close)    ensure_root "$@"; do_close ;;
    small)        ensure_root "$@"; do_small ;;
    status)       ensure_root "$@"; do_status ;;
    diag)         ensure_root "$@"; do_diag ;;
    watchdog)     ensure_root "$@"; do_watchdog ;;
    raw)          ensure_root "$@"; exec "$@" ;;
    *)
        cat <<EOF
BYD 仪表飞屏 · root 版

用法：
  sh $0 on         开启全屏导航（飞屏）
  sh $0 off        关闭
  sh $0 small      切小屏导航
  sh $0 status     查看当前仪表导航类型
  sh $0 diag       环境自检（先跑这个）
  sh $0 raw <cmd>  直接执行一条命令
  sh $0 watchdog   守护循环（开机脚本调用）

日志：$LOG
EOF
        ;;
esac
