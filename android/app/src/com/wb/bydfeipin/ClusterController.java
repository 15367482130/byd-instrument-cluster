package com.wb.bydfeipin;

import java.io.IOException;

/**
 * 仪表飞屏的控制逻辑（与 PC 版工具完全一致的命令序列）。
 *
 * <pre>
 * 开启：
 *   1. 启动车机自带调试代理 com.byd.clusterdebug
 *   2. INSTRUMENT_NAVI_TYPE = 4（全屏导航）
 *   3. AutoContainer 35（创建 Di4.0 投影显示）→ 16（全屏投影）
 *   4. 启动定制版地图
 * 关闭：
 *   AutoContainer 18 + INSTRUMENT_NAVI_TYPE = 1
 * </pre>
 */
public class ClusterController {

    public static final int DEVICE_ID = 1007;
    public static final int READ_TRANSACTION = 5;
    public static final int SET_TRANSACTION = 6;
    /** 0x40C03032 读 INSTRUMENT_NAVI_TYPE */
    public static final long FEATURE_READ = 1086337074L;
    /** 0x4C10A018 写 INSTRUMENT_NAVI_TYPE_SET */
    public static final long FEATURE_SET = 1276157976L;

    private final Shell adb;
    private final StringBuilder log = new StringBuilder();

    public ClusterController(Shell adb) {
        this.adb = adb;
    }

    public String getLog() {
        return log.toString();
    }

    private void clearLog() {
        log.setLength(0);
    }

    private String run(String title, String cmd) {
        try {
            String out = adb.shell(cmd);
            boolean bad = isError(out);
            log.append(bad ? "[!!] " : "[OK] ").append(title).append('\n');
            log.append("     $ ").append(cmd).append('\n');
            if (out != null && out.trim().length() > 0) {
                log.append("     ").append(out.trim().replace("\n", "\n     ")).append('\n');
            }
            log.append('\n');
            return out;
        } catch (Exception e) {
            log.append("[!!] ").append(title).append(" 失败：").append(e.getMessage()).append('\n');
            log.append("     $ ").append(cmd).append("\n\n");
            return "";
        }
    }

    private static boolean isError(String out) {
        if (out == null) return true;
        String s = out.toLowerCase();
        return s.contains("exception") || s.contains("permission denial")
                || s.contains("not found") || s.contains("no such")
                || s.contains("unknown") || s.contains("cannot find")
                || s.contains("unable to");
    }

    /** 读取当前仪表导航类型，返回 1/2/3/4，失败返回 -1。 */
    public int readNaviType() {
        String out = run("读取仪表导航类型",
                "service call autoservice " + READ_TRANSACTION + " i32 " + DEVICE_ID + " i32 " + FEATURE_READ);
        return parseParcelInt(out);
    }

    private static int parseParcelInt(String reply) {
        if (reply == null) return -1;
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile("([0-9a-fA-F]{8})").matcher(reply);
        String last = null;
        while (m.find()) last = m.group(1);
        if (last == null) return -1;
        try {
            return (int) Long.parseLong(last, 16);
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    /** 开启飞屏。若 mapPackage 为 null 则自动探测。 */
    public boolean enable(String mapPackage) {
        clearLog();
        log.append(">>> 开启仪表飞屏\n\n");

        run("启动调试代理服务", "am startservice -n com.byd.clusterdebug/.ClusterDebugService");
        run("打开调试代理界面", "am start -n com.byd.clusterdebug/.MainActivity");

        run("设置仪表导航类型 = 全屏(4)",
                "service call autoservice " + SET_TRANSACTION + " i32 " + DEVICE_ID
                        + " i32 " + FEATURE_SET + " i32 4");

        run("创建 Di4.0 投影显示(35)",
                "service call AutoContainer 2 i32 1000 s16 \"35\"");
        try {
            Thread.sleep(1000);
        } catch (InterruptedException ignored) {
        }
        run("打开全屏投影(16)",
                "service call AutoContainer 2 i32 1000 s16 \"16\"");

        String pkg = mapPackage;
        if (pkg == null || pkg.isEmpty()) {
            pkg = detectMapPackage();
        }
        if (pkg != null) {
            run("启动地图 " + pkg,
                    "monkey -p " + pkg + " -c android.intent.category.LAUNCHER 1");
        } else {
            log.append("[!!] 未找到定制版地图包，请手动打开导航\n\n");
        }

        int now = readNaviType();
        log.append("当前仪表导航类型 = ").append(now).append('\n');
        return now == 4;
    }

    /** 关闭飞屏。 */
    public boolean disable() {
        clearLog();
        log.append(">>> 关闭仪表飞屏\n\n");
        run("关闭投影(18)", "service call AutoContainer 2 i32 1000 s16 \"18\"");
        run("恢复仪表导航类型 = 关闭(1)",
                "service call autoservice " + SET_TRANSACTION + " i32 " + DEVICE_ID
                        + " i32 " + FEATURE_SET + " i32 1");
        return true;
    }

    /** 切换小屏导航。 */
    public boolean small() {
        clearLog();
        log.append(">>> 切换小屏导航\n\n");
        run("设置仪表导航类型 = 小屏(3)",
                "service call autoservice " + SET_TRANSACTION + " i32 " + DEVICE_ID
                        + " i32 " + FEATURE_SET + " i32 3");
        run("半屏投影(17)", "service call AutoContainer 2 i32 1000 s16 \"17\"");
        return true;
    }

    /** 探测车机上的定制版地图包名。 */
    public String detectMapPackage() {
        String out = run("枚举地图相关包", "pm list packages");
        if (out == null) return null;
        String best = null;
        int bestRank = 99;
        String[] priority = {"autonavi.minimap.byd", "byd.amap", "byd.autonavi", "autonavi", "baidu", "bmap"};
        String[] keys = {"autonavi", "amap", "baidu", "bmap", "tencent", "byd"};
        for (String line : out.split("\n")) {
            line = line.trim();
            if (!line.startsWith("package:")) continue;
            String pkg = line.substring("package:".length()).trim();
            String low = pkg.toLowerCase();
            boolean hit = false;
            for (String k : keys) if (low.contains(k)) { hit = true; break; }
            if (!hit) continue;
            int rank = 99;
            for (int i = 0; i < priority.length; i++) {
                if (low.contains(priority[i])) { rank = i; break; }
            }
            if (rank < bestRank) { bestRank = rank; best = pkg; }
        }
        return best;
    }

    /** 控制器自检信息。 */
    public String diagnose() {
        clearLog();
        log.append("=== 系统版本 ===\n");
        run("Android 版本", "getprop ro.build.version.release");
        run("车型", "getprop ro.product.model");
        run("固件", "getprop ro.build.display.id");
        run("控制器属性", "getprop | grep -iE 'ivi|controller|cluster|byd' | head -30");
        run("ClusterDebug", "pm list packages | grep -i clusterdebug");
        run("相关包", "pm list packages | grep -iE 'autonavi|amap|baidu|bmap|xdja'");
        readNaviType();
        return log.toString();
    }
}
