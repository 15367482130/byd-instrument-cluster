package com.wb.bydfeipin;

import android.content.Context;

import java.security.PrivateKey;

/**
 * 取得一个可用的 shell 通道：<b>优先 root，其次 ADB</b>。
 *
 * <p>车机已 root（Magisk / KernelSU）时走 {@link RootShell} ——
 * 不需要开「无线 ADB 调试」、不需要 5555 端口、不需要授权弹窗，重启也不会失效。
 * 没 root 或用户手动切成「仅 ADB」时，退回原来的 {@link AdbClient} 连本机 adbd。
 *
 * <p>这也是「开机自动开启」最可靠的一条路：{@link FeipinService} 开机直接
 * 用 root 执行，不必依赖那个每次重启都会被关掉的无线调试开关。
 */
public final class AdbManager {

    public static final String HOST = "127.0.0.1";

    private static Shell shell;

    private AdbManager() {}

    /** 用界面/配置里的端口（仅在退回 ADB 时才会用到端口）。 */
    public static synchronized Shell get(Context ctx, int timeoutMs) throws Exception {
        return get(ctx, Prefs.getPort(ctx), timeoutMs);
    }

    /** 取得一个可用通道；已建立且仍可用时直接复用。 */
    public static synchronized Shell get(Context ctx, int port, int timeoutMs) throws Exception {
        if (shell != null && shell.isConnected()) {
            return shell;
        }
        reset();

        if (Prefs.isPreferRoot(ctx) && RootShell.available(ctx)) {
            shell = RootShell.open(ctx, timeoutMs);
            return shell;
        }
        shell = adbConnect(ctx, port, timeoutMs);
        return shell;
    }

    /** 强制走 ADB（供 ADB 端口回退逻辑使用）。 */
    public static synchronized AdbClient getAdbOnly(Context ctx, int port, int timeoutMs) throws Exception {
        if (shell instanceof AdbClient && shell.isConnected()) {
            return (AdbClient) shell;
        }
        reset();
        AdbClient c = adbConnect(ctx, port, timeoutMs);
        shell = c;
        return c;
    }

    private static AdbClient adbConnect(Context ctx, int port, int timeoutMs) throws Exception {
        PrivateKey key = Prefs.getPrivateKey(ctx);
        String pub = Prefs.getPublicKey(ctx);
        AdbClient c = new AdbClient(key, pub);
        c.connect(HOST, port, timeoutMs);
        return c;
    }

    public static synchronized void reset() {
        if (shell != null) {
            shell.close();
            shell = null;
        }
    }

    public static synchronized boolean isReady() {
        return shell != null && shell.isConnected();
    }

    /** 当前实际使用的通道名（{@code "root"} / {@code "ADB"} / {@code "-"}），供界面显示。 */
    public static synchronized String mode() {
        return shell == null ? "-" : shell.mode();
    }
}
