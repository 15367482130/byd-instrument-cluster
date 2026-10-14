package com.wb.bydfeipin;

/**
 * 执行 shell 命令的统一接口。
 *
 * <p>两种实现：
 * <ul>
 *   <li>{@link RootShell} —— 车机已 root 时用 {@code su} 直接执行。<b>不需要 ADB</b>。</li>
 *   <li>{@link AdbClient} —— 没 root 时连本机 adbd（{@code 127.0.0.1:5555}）。</li>
 * </ul>
 *
 * <p>{@link ClusterController} 里的命令序列对两者完全一致 ——
 * {@code autoservice} / {@code AutoContainer} 只检查调用者身份，
 * root 的 uid 0 比 shell 还高，所以能直接调，省掉开无线调试、端口、授权弹窗那一整套。
 */
public interface Shell {

    /** 执行一条命令，返回输出（stdout 与 stderr 合并）。 */
    String shell(String command) throws Exception;

    boolean isConnected();

    void close();

    /** 用于界面显示的通道名，如 {@code "root"} / {@code "ADB"}。 */
    String mode();
}
