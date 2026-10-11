package com.wb.bydfeipin;

import android.content.Context;

import java.security.PrivateKey;

/** 负责连接车机本机的 adbd（127.0.0.1:5555）并缓存连接。 */
public final class AdbManager {

    public static final String HOST = "127.0.0.1";

    private static AdbClient client;

    private AdbManager() {}

    /** 取得一个已连接的客户端；未连接或已断开时会重新连接。 */
    public static synchronized AdbClient get(Context ctx, int port, int timeoutMs) throws Exception {
        if (client != null && client.isConnected()) {
            return client;
        }
        if (client != null) {
            client.close();
            client = null;
        }
        PrivateKey key = Prefs.getPrivateKey(ctx);
        String pub = Prefs.getPublicKey(ctx);
        AdbClient c = new AdbClient(key, pub);
        c.connect(HOST, port, timeoutMs);
        client = c;
        return c;
    }

    /** 用当前配置的端口连接。 */
    public static AdbClient get(Context ctx, int timeoutMs) throws Exception {
        return get(ctx, Prefs.getPort(ctx), timeoutMs);
    }

    public static synchronized void reset() {
        if (client != null) {
            client.close();
            client = null;
        }
    }

    public static synchronized boolean isReady() {
        return client != null && client.isConnected();
    }
}
