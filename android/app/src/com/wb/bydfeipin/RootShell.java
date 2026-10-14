package com.wb.bydfeipin;

import android.content.Context;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.concurrent.TimeUnit;

/**
 * 通过 {@code su} 以 root 身份执行命令 —— 已 root 的车机推荐走这条通道。
 *
 * <p>为什么 root 之后就不需要 ADB：{@code autoservice} / {@code AutoContainer}
 * 只检查调用者身份，普通 App 会被拒，所以社区方案要绕道去拿一个 shell 身份。
 * root 的 uid 0 比 shell 还高，直接调即可 —— 于是「开无线调试 / 记 5555 端口 /
 * 授权弹窗 / 重启失效」这几个问题**全部不存在**。
 *
 * <p>实现上走的是「一条命令起一个 su 进程」，而不是常驻 shell：
 * Magisk 的 su 在管道环境下可能分配 PTY 并把命令回显出来，
 * 常驻方案要靠标记行解析输出、容易串行；一次性执行最稳。
 */
public final class RootShell implements Shell {

    /** 常见 su 路径，按优先级探测。 */
    private static final String[] SU_PATHS = {
            "/system/bin/su",
            "/system/xbin/su",
            "/sbin/su",
            "/debug_ramdisk/su",
            "/data/adb/ksu/bin/su",
            "/data/adb/magisk/su",
    };

    private static String suBin;
    private static Boolean probeResult;
    private static String probeDetail = "";

    private final String bin;
    private final int timeoutMs;

    private RootShell(String bin, int timeoutMs) {
        this.bin = bin;
        this.timeoutMs = timeoutMs;
    }

    // ------------------------------------------------------------ 探测

    /** 找到看起来可用的 su；都找不到就退回 PATH 里的 {@code su}。 */
    public static synchronized String findSu() {
        if (suBin != null) {
            return suBin;
        }
        for (String p : SU_PATHS) {
            try {
                if (new File(p).exists()) {
                    suBin = p;
                    return suBin;
                }
            } catch (Throwable ignored) {
                // 继续找下一个
            }
        }
        suBin = "su";
        return suBin;
    }

    /** 上一次探测的说明文字，用于界面展示。 */
    public static synchronized String probeDetail() {
        return probeDetail;
    }

    /**
     * 探测 root 是否可用。第一次调用会触发 Magisk / KernelSU 的授权弹窗，结果会被缓存。
     *
     * @return true 表示已拿到 uid 0
     */
    public static synchronized boolean available(Context ctx) {
        if (probeResult != null) {
            return probeResult;
        }
        String out;
        try {
            out = rawExec(findSu(), "id -u", 25000).trim();
        } catch (Exception e) {
            probeDetail = "执行 su 失败：" + e.getMessage() + "（未 root？）";
            probeResult = false;
            if (ctx != null) {
                Prefs.setRootOk(ctx, false);
            }
            return false;
        }
        String last = out.isEmpty() ? "" : out.substring(out.lastIndexOf('\n') + 1).trim();
        boolean ok = "0".equals(last) || out.contains("uid=0");
        probeResult = ok;
        probeDetail = ok
                ? ("root 可用：" + findSu())
                : ("su 执行成功但 uid 不是 0（输出：" + oneLine(out) + "）");
        if (ctx != null) {
            Prefs.setRootOk(ctx, ok);
        }
        return ok;
    }

    /** 清掉探测缓存（用户切换连接方式时用）。 */
    public static synchronized void resetProbe() {
        probeResult = null;
        probeDetail = "";
    }

    public static RootShell open(Context ctx, int timeoutMs) throws IOException {
        if (!available(ctx)) {
            throw new IOException("root 不可用 —— " + probeDetail);
        }
        return new RootShell(findSu(), timeoutMs);
    }

    // ------------------------------------------------------------ Shell

    @Override
    public String shell(String command) throws Exception {
        return rawExec(bin, command, timeoutMs);
    }

    @Override
    public boolean isConnected() {
        return true;   // 每条命令都是新进程，不存在长连接
    }

    @Override
    public void close() {
        // 无常驻资源
    }

    @Override
    public String mode() {
        return "root";
    }

    // ------------------------------------------------------------ 执行

    private static String rawExec(final String bin, final String cmd, int timeoutMs) throws IOException {
        // 用参数数组传命令，避免自己拼 shell 引号
        ProcessBuilder pb = new ProcessBuilder(bin, "-c", cmd);
        pb.redirectErrorStream(true);

        final Process p;
        try {
            p = pb.start();
        } catch (IOException e) {
            throw new IOException("无法执行 " + bin + "：" + e.getMessage());
        }
        try {
            p.getOutputStream().close();
        } catch (IOException ignored) {
            // 忽略
        }

        final ByteArrayOutputStream buf = new ByteArrayOutputStream();
        Thread reader = new Thread(new Runnable() {
            @Override
            public void run() {
                InputStream is = null;
                try {
                    is = p.getInputStream();
                    byte[] b = new byte[4096];
                    int n;
                    while ((n = is.read(b)) > 0) {
                        buf.write(b, 0, n);
                    }
                } catch (IOException ignored) {
                    // 进程被 destroy 时正常
                } finally {
                    if (is != null) {
                        try {
                            is.close();
                        } catch (IOException ignored) {
                            // 忽略
                        }
                    }
                }
            }
        }, "root-reader");
        reader.setDaemon(true);
        reader.start();

        boolean done;
        try {
            done = p.waitFor(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            p.destroy();
            throw new IOException("被中断");
        }
        if (!done) {
            p.destroy();
            throw new IOException("su 命令超时（" + timeoutMs + " ms）");
        }
        try {
            reader.join(800);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }

        int code = p.exitValue();
        String out = buf.toString("UTF-8");
        if (code != 0 && out.trim().isEmpty()) {
            throw new IOException("su 退出码 " + code);
        }
        return out;
    }

    private static String oneLine(String s) {
        if (s == null) {
            return "";
        }
        String t = s.replace('\n', ' ').replace('\r', ' ').trim();
        return t.length() > 120 ? t.substring(0, 120) + "…" : t;
    }
}
