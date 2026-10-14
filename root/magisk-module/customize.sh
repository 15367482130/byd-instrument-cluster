#!/system/bin/sh
# ------------------------------------------------------------
# Magisk / KernelSU 模块安装时执行
# ------------------------------------------------------------

SKIPMOUNT=true
PROPFILE=false
POSTFSDATA=false
LATESTARTSERVICE=true

ui_print " "
ui_print "*******************************"
ui_print " BYD 仪表飞屏 · 开机自动开启"
ui_print "*******************************"
ui_print " "
ui_print "- 主脚本  : byd-feipin.sh"
ui_print "- 日志    : /data/adb/byd-feipin.log"
ui_print "- 配置    : /data/adb/byd-feipin.conf（首次开机会自动生成）"
ui_print " "
ui_print "- 默认行为: 开机后自动开启「仪表全屏导航」"
ui_print "- 想常驻守护（掉了自动重开）: 把配置里的 LOOP 改成 1"
ui_print " "

set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/byd-feipin.sh" 0 0 0755
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/customize.sh" 0 0 0755
