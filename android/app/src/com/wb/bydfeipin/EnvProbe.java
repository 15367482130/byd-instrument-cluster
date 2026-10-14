package com.wb.bydfeipin;

import android.content.Context;
import android.os.Build;
import android.provider.Settings;

/**
 * 本机 ADB 环境探测。
 *
 * <p>为什么需要它：Android 11 起「无线调试」改成了 <b>TLS 加密 + 随机临时端口</b>
 * （典型 37000–45000，且还分「配对端口」和「连接端口」两个），**不再监听 5555**。
 * 而车机（DiLink）上的 BYD「无线 adb 调试」开关走的是经典 {@code service.adb.tcp.port}，
 * 就是 5555 明文。两者现象完全一样（连不上），原因却不同 —— 所以要把它们区分出来。
 *
 * <p>这里只用「读」权限做诊断，不修改任何系统设置：
 * <ul>
 *   <li>{@code Settings.Global} 读 USB 调试、无线调试的总开关状态；</li>
 *   <li>反射读 {@code service.adb.tcp.port}（明文）/ {@code service.adb.tls.port}（TLS）。</li>
 * </ul>
 * 反射被非 SDK 接口限制拦掉时返回默认值，不影响主流程。
 */
public final class EnvProbe {

    /** 读取失败时的返回值（-1 = 未知/未设置）。 */
    public static final int UNKNOWN = -1;

    private EnvProbe() {}

    /** 反射读系统属性；失败返回 def。 */
    public static int sysPropInt(String key, int def) {
        try {
            Class<?> sp = Class.forName("android.os.SystemProperties");
            java.lang.reflect.Method get = sp.getMethod("get", String.class, String.class);
            Object v = get.invoke(null, key, "");
            if (v == null) return def;
            String s = v.toString().trim();
            if (s.isEmpty()) return def;
            return Integer.parseInt(s);
        } catch (Throwable t) {
            return def;
        }
    }

    /** 读 Settings.Global 的整数开关；失败返回 UNKNOWN。 */
    private static int globalInt(Context c, String key) {
        try {
            return Settings.Global.getInt(c.getContentResolver(), key, UNKNOWN);
        } catch (Throwable t) {
            return UNKNOWN;
        }
    }

    /** 明文 TCP 端口（经典 adb tcpip / BYD 无线adb调试开关）。 */
    public static int plainTcpPort() {
        return sysPropInt("service.adb.tcp.port", UNKNOWN);
    }

    /** Android 11+ 无线调试的 TLS 端口。 */
    public static int tlsPort() {
        return sysPropInt("service.adb.tls.port", UNKNOWN);
    }

    public static boolean usbDebugEnabled(Context c) {
        return globalInt(c, Settings.Global.ADB_ENABLED) == 1;
    }

    public static boolean wirelessDebugEnabled(Context c) {
        return globalInt(c, "adb_wifi_enabled") == 1;
    }

    /** 该给用户看的候选端口列表（去重，按可能性排序）。 */
    public static int[] candidatePorts(Context c, int configured) {
        java.util.LinkedHashSet<Integer> set = new java.util.LinkedHashSet<>();
        addIfValid(set, configured);
        addIfValid(set, plainTcpPort());
        addIfValid(set, 5555);
        int[] out = new int[set.size()];
        int i = 0;
        for (int p : set) out[i++] = p;
        return out;
    }

    private static void addIfValid(java.util.Set<Integer> set, int p) {
        if (p > 0 && p < 65536) set.add(p);
    }

    /**
     * 连接失败时的精准诊断。返回可直接打进日志的多行文本。
     *
     * @param triedPort 这次实际尝试的端口
     */
    public static String diagnose(Context c, int triedPort) {
        int sdk = Build.VERSION.SDK_INT;
        int tcp = plainTcpPort();
        int tls = tlsPort();
        boolean usb = usbDebugEnabled(c);
        boolean wifi = wirelessDebugEnabled(c);

        StringBuilder sb = new StringBuilder();
        sb.append("=== 本机环境探测 ===\n");

        // ---- root 通道优先判断：有 root 就不需要 ADB 这一套 ----
        boolean preferRoot = Prefs.isPreferRoot(c);
        boolean rootOk = Prefs.isRootOk(c);
        String rootDetail = RootShell.probeDetail();
        if (preferRoot && !rootOk) {
            rootOk = RootShell.available(c);
            rootDetail = RootShell.probeDetail();
        }
        sb.append("root 可用             : ").append(tri(rootOk)).append('\n');
        if (rootDetail != null && rootDetail.length() > 0) {
            sb.append("  ").append(rootDetail).append('\n');
        }
        sb.append("连接方式偏好          : ").append(preferRoot ? "root 优先" : "仅 ADB")
                .append(preferRoot ? "" : "（可在界面上切换回 root 优先）").append("\n\n");

        sb.append("--- ADB 环境 ---\n");
        sb.append("Android 版本          : ").append(Build.VERSION.RELEASE)
                .append("  (API ").append(sdk).append(")\n");
        sb.append("USB 调试开关          : ").append(tri(usb)).append('\n');
        sb.append("「无线调试」开关      : ").append(tri(wifi)).append('\n');
        sb.append("service.adb.tcp.port  : ").append(port(tcp))
                .append(tcp > 0 ? "   ← 明文 TCP，可用" : "   ← 明文 TCP 未开启").append('\n');
        sb.append("service.adb.tls.port  : ").append(port(tls))
                .append(tls > 0 ? "   ← TLS 加密，本工具用不了" : "").append('\n');
        sb.append("本次尝试端口          : ").append(triedPort).append("\n\n");

        // ---- 结论 ----
        if (rootOk) {
            sb.append("【结论】已检测到 root。直接用 root 通道即可 ——\n");
            sb.append("        autoservice / AutoContainer 只检查调用者身份，uid 0 比 shell 还高，\n");
            sb.append("        所以不需要「无线调试」开关、不需要 5555 端口、不用授权弹窗，重启也不会失效。\n");
            sb.append("【若仍失败】确认固件确实是 18.x / 21.x 控制器；可点「检测 root」看 su 的详细输出。\n");
        } else if (tls > 0 && tcp <= 0) {
            sb.append("【结论】当前处于 Android 11+ 的「无线调试」模式。\n");
            sb.append("        它不监听 5555，而是随机端口 + TLS 加密 + 需要配对，\n");
            sb.append("        普通程序无法用第 5555 端口那一套协议连上去。\n");
            sb.append("【怎么办】改用经典明文模式（任选一种）：\n");
            sb.append("  1) 电脑用 USB 线连本机 → 执行  adb tcpip ").append(triedPort > 0 ? triedPort : 5555).append("\n");
            sb.append("     拔掉线后再点「连接 / 授权」即可。重启后会失效，需重做。\n");
            sb.append("  2) 若这是比亚迪车机：到 车辆设置 → 版本管理 → 连续点「恢复出厂设置」，\n");
            sb.append("     打开「无线 adb 调试」开关（BYD 的实现走 5555 明文）——本工具正是给它用的。\n");
        } else if (sdk >= 30 && tcp <= 0) {
            sb.append("【结论】Android 11+ 上端口 ").append(triedPort).append(" 没人监听。\n");
            sb.append("        请先执行一次  adb tcpip ").append(triedPort)
                    .append("（需电脑 USB 连接）。\n");
        } else if (!usb) {
            sb.append("【结论】「USB 调试」总开关是关的，adbd 不会接受任何连接。\n");
            sb.append("        请到 开发者选项 打开「USB 调试」。\n");
        } else {
            sb.append("【结论】端口 ").append(triedPort).append(" 没有服务在监听（adbd 未运行在该端口）。\n");
            sb.append("        可依次排查：\n");
            sb.append("  · 车机请打开「无线 adb 调试」开关（BYD 走 5555）\n");
            sb.append("  · 若端口改过，在上面的「ADB 端口」里填对再连\n");
            sb.append("  · 重启车机/手机后 adbd 会退回 USB 模式，需重新开启\n");
        }
        return sb.toString();
    }

    private static String tri(boolean b) {
        return b ? "开" : "关";
    }

    private static String port(int p) {
        return p > 0 ? String.valueOf(p) : "未设置";
    }
}
