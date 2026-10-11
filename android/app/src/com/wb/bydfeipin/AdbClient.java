package com.wb.bydfeipin;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.PrivateKey;

/**
 * 一个极简的 ADB 客户端实现（纯 Java，不依赖 adb 可执行文件）。
 *
 * <p>用途：让车机上的 App 直接连本机 adbd（127.0.0.1:5555），以 shell 身份
 * 执行命令——因为 autoservice / AutoContainer 这类 Binder 需要 shell 权限，
 * 普通 App 无法直接调用。
 *
 * <p>实现内容：CNXN 握手 → RSA AUTH（token 签名，失败则上报公钥等待授权）
 * → OPEN "shell:cmd" → 收 WRTE 数据 → CLSE 结束。
 */
public class AdbClient {

    // ---- 协议常量 ----
    private static final int A_CNXN = 0x4e584e43;
    private static final int A_AUTH = 0x48545541;
    private static final int A_OPEN = 0x4e45504f;
    private static final int A_OKAY = 0x59414b4f;
    private static final int A_WRTE = 0x45545257;
    private static final int A_CLSE = 0x45534c43;

    private static final int AUTH_TOKEN = 1;
    private static final int AUTH_SIGNATURE = 2;
    private static final int AUTH_RSAPUBLICKEY = 3;

    private static final int VERSION = 0x01000001;
    private static final int MAXDATA = 4096;

    private final PrivateKey privateKey;
    private final String publicKeyString;

    private Socket socket;
    private InputStream in;
    private OutputStream out;
    private int nextLocalId = 1;

    public AdbClient(PrivateKey privateKey, String publicKeyString) {
        this.privateKey = privateKey;
        this.publicKeyString = publicKeyString;
    }

    public boolean isConnected() {
        return socket != null && socket.isConnected() && !socket.isClosed();
    }

    /**
     * 连接并完成授权。
     *
     * @param authTimeoutMs 等待用户在车机上点「允许」的最长时间
     */
    public void connect(String host, int port, int authTimeoutMs) throws IOException {
        close();

        Socket s = new Socket();
        s.connect(new InetSocketAddress(host, port), 8000);
        s.setTcpNoDelay(true);
        s.setSoTimeout(authTimeoutMs);
        socket = s;
        in = s.getInputStream();
        out = s.getOutputStream();

        // 1) CNXN：以 host 身份握手，不声明 shell_v2，使用最简的传统 shell 流
        send(A_CNXN, VERSION, MAXDATA, "host::\u0000".getBytes(StandardCharsets.UTF_8));

        boolean sentSignature = false;
        boolean sentPublicKey = false;
        long deadline = System.currentTimeMillis() + authTimeoutMs;

        while (System.currentTimeMillis() < deadline) {
            Msg m = read();
            if (m == null) {
                throw new IOException("连接被对方关闭");
            }
            if (m.cmd == A_CNXN) {
                socket.setSoTimeout(30000);     // 授权完成，恢复正常读超时
                return;
            }
            if (m.cmd == A_AUTH) {
                if (m.arg0 == AUTH_TOKEN) {
                    if (!sentSignature) {
                        // 先用本机私钥对 token 签名（已被授权过时这一步就够了）
                        byte[] sig;
                        try {
                            sig = RsaKeyUtil.signToken(privateKey, m.data);
                        } catch (Exception e) {
                            throw new IOException("签名失败：" + e.getMessage(), e);
                        }
                        send(A_AUTH, AUTH_SIGNATURE, 0, sig);
                        sentSignature = true;
                    } else if (!sentPublicKey) {
                        // 签名不被识别 —— 上报公钥，车机会弹「允许调试」对话框
                        send(A_AUTH, AUTH_RSAPUBLICKEY, 0, pubkeyPayload());
                        sentPublicKey = true;
                    }
                } else if (m.arg0 == AUTH_RSAPUBLICKEY) {
                    if (!sentPublicKey) {
                        send(A_AUTH, AUTH_RSAPUBLICKEY, 0, pubkeyPayload());
                        sentPublicKey = true;
                    }
                }
            } else if (m.cmd == A_CLSE) {
                throw new IOException("adbd 拒绝了连接（无线调试是否已打开？）");
            }
            // 其它消息忽略
        }
        throw new IOException("等待授权超时。请在车机弹出的「允许 USB 调试」里点允许。");
    }

    private byte[] pubkeyPayload() {
        byte[] k = publicKeyString.getBytes(StandardCharsets.UTF_8);
        byte[] withNul = new byte[k.length + 1];
        System.arraycopy(k, 0, withNul, 0, k.length);
        return withNul;                       // adbd 以 NUL 结尾的字符串解析
    }

    /** 以 shell 身份执行命令并返回输出。 */
    public String shell(String command) throws IOException {
        if (!isConnected()) {
            throw new IOException("尚未连接");
        }
        int local = nextLocalId++;
        send(A_OPEN, local, 0, ("shell:" + command + "\u0000").getBytes(StandardCharsets.UTF_8));

        int remote = -1;
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        while (true) {
            Msg m = read();
            if (m == null) break;

            if (m.cmd == A_OKAY && m.arg1 == local) {
                remote = m.arg0;
            } else if (m.cmd == A_WRTE && (remote < 0 || m.arg0 == remote)) {
                if (remote < 0) remote = m.arg0;
                if (m.data != null) buf.write(m.data);
                send(A_OKAY, local, remote, null);      // 应答，放行后续数据
            } else if (m.cmd == A_CLSE) {
                if (remote < 0 || m.arg0 == remote) break;
            }
        }
        return new String(buf.toByteArray(), StandardCharsets.UTF_8).replace("\r", "");
    }

    public void close() {
        try {
            if (socket != null) socket.close();
        } catch (IOException ignored) {
        }
        socket = null;
        in = null;
        out = null;
    }

    // ---- 收发 ----

    private void send(int cmd, int arg0, int arg1, byte[] data) throws IOException {
        int len = data == null ? 0 : data.length;
        byte[] header = new byte[24];
        putInt(header, 0, cmd);
        putInt(header, 4, arg0);
        putInt(header, 8, arg1);
        putInt(header, 12, len);
        putInt(header, 16, checksum(data));
        putInt(header, 20, cmd ^ 0xFFFFFFFF);
        out.write(header);
        if (len > 0) out.write(data);
        out.flush();
    }

    private Msg read() throws IOException {
        byte[] header = readFully(24);
        if (header == null) return null;
        Msg m = new Msg();
        m.cmd = getInt(header, 0);
        m.arg0 = getInt(header, 4);
        m.arg1 = getInt(header, 8);
        int len = getInt(header, 12);
        if (len < 0 || len > 4 * 1024 * 1024) {
            throw new IOException("非法的数据长度：" + len);
        }
        m.data = len > 0 ? readFully(len) : new byte[0];
        return m;
    }

    private byte[] readFully(int n) throws IOException {
        byte[] b = new byte[n];
        int off = 0;
        while (off < n) {
            int r;
            try {
                r = in.read(b, off, n - off);
            } catch (java.net.SocketTimeoutException e) {
                if (off == 0 && n == 24) return null;   // 空闲超时
                throw e;
            }
            if (r < 0) return off == 0 ? null : b;
            off += r;
        }
        return b;
    }

    private static int checksum(byte[] data) {
        int sum = 0;
        if (data != null) for (byte b : data) sum += (b & 0xFF);
        return sum;
    }

    private static void putInt(byte[] b, int off, int v) {
        b[off] = (byte) (v & 0xFF);
        b[off + 1] = (byte) ((v >>> 8) & 0xFF);
        b[off + 2] = (byte) ((v >>> 16) & 0xFF);
        b[off + 3] = (byte) ((v >>> 24) & 0xFF);
    }

    private static int getInt(byte[] b, int off) {
        return (b[off] & 0xFF)
                | ((b[off + 1] & 0xFF) << 8)
                | ((b[off + 2] & 0xFF) << 16)
                | ((b[off + 3] & 0xFF) << 24);
    }

    private static final class Msg {
        int cmd, arg0, arg1;
        byte[] data;
    }
}
