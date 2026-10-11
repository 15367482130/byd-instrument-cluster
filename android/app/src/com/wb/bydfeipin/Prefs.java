package com.wb.bydfeipin;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;

import java.security.KeyPair;
import java.security.PrivateKey;
import java.security.interfaces.RSAPublicKey;

/** 配置与 ADB 密钥的本地存储。 */
public final class Prefs {

    private static final String FILE = "bydfeipin";
    private static final String K_PRIV = "adb_priv_pkcs8";
    private static final String K_PUB = "adb_pub_string";
    private static final String K_AUTO = "auto_start";
    private static final String K_PORT = "adb_port";
    private static final String K_MAP = "map_package";
    private static final String K_LOG = "last_log";

    private Prefs() {}

    private static SharedPreferences sp(Context c) {
        return c.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** 取本机 ADB 私钥；首次调用时自动生成 2048 位 RSA 密钥对并保存。 */
    public static synchronized PrivateKey getPrivateKey(Context c) {
        SharedPreferences p = sp(c);
        String s = p.getString(K_PRIV, null);
        try {
            if (s != null) {
                return RsaKeyUtil.loadPrivateKey(Base64.decode(s, Base64.NO_WRAP));
            }
            KeyPair kp = RsaKeyUtil.generateKeyPair();
            p.edit()
                    .putString(K_PRIV, Base64.encodeToString(kp.getPrivate().getEncoded(), Base64.NO_WRAP))
                    .putString(K_PUB, RsaKeyUtil.buildPublicKeyString((RSAPublicKey) kp.getPublic()))
                    .apply();
            return kp.getPrivate();
        } catch (Exception e) {
            throw new RuntimeException("生成 ADB 密钥失败：" + e.getMessage(), e);
        }
    }

    public static String getPublicKey(Context c) {
        getPrivateKey(c);                     // 确保已生成
        return sp(c).getString(K_PUB, "");
    }

    public static boolean isAutoStart(Context c) {
        return sp(c).getBoolean(K_AUTO, false);
    }

    public static void setAutoStart(Context c, boolean v) {
        sp(c).edit().putBoolean(K_AUTO, v).apply();
    }

    public static int getPort(Context c) {
        return sp(c).getInt(K_PORT, 5555);
    }

    public static void setPort(Context c, int v) {
        sp(c).edit().putInt(K_PORT, v).apply();
    }

    public static String getMapPackage(Context c) {
        return sp(c).getString(K_MAP, null);
    }

    public static void setMapPackage(Context c, String v) {
        sp(c).edit().putString(K_MAP, v).apply();
    }

    public static String getLastLog(Context c) {
        return sp(c).getString(K_LOG, "");
    }

    public static void setLastLog(Context c, String v) {
        sp(c).edit().putString(K_LOG, v).apply();
    }
}
