package com.wb.bydfeipin;

import android.app.Activity;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/**
 * 车机端主界面：一键开关仪表飞屏。
 *
 * <p>界面全部用代码构建，避免依赖额外资源。
 *
 * <p><b>横屏适配</b>：车机屏幕普遍是横屏且高度矮。若沿用竖排布局，标题 + 状态 +
 * 三排按钮会把日志区挤成 0 高度，整页又无法滚动，导致「上下滑不动」。
 * 因此这里按屏幕方向切换布局：
 * <ul>
 *   <li>横屏（宽 &gt; 高）：左右分栏 —— 左侧控制面板（独立 ScrollView，可上下滑），
 *       右侧日志占满整屏高度（独立 ScrollView）。两边互不影响。</li>
 *   <li>竖屏：上下结构 —— 上方控制面板（可滚动），下方日志占剩余空间。</li>
 * </ul>
 */
public class MainActivity extends Activity {

    private final Handler ui = new Handler(Looper.getMainLooper());

    private LinearLayout root;
    private TextView status;
    private TextView logView;
    private ScrollView logScroll;
    private Button autoBtn;
    private EditText portInput;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        if (logView.getText().length() == 0) {
            appendLog("就绪。\n前置条件：车机「开发者选项」里已打开「连接USB后启用调试模式」和「无线ADB调试」。\n"
                    + "首次点「连接 / 授权」时，车机会弹出「允许 USB 调试」，请勾选始终允许。");
        }
    }

    /** 旋转屏幕时不重建 Activity，只重排布局，避免日志与状态丢失。 */
    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        String keepLog = logView == null ? "" : logView.getText().toString();
        String keepStatus = status == null ? null : status.getText().toString();
        buildUi();
        logView.setText(keepLog);
        if (keepStatus != null) status.setText(keepStatus);
        scrollLogToEnd();
    }

    @Override
    public void onBackPressed() {
        // 车机上误触返回容易让人以为程序坏了，这里直接退到后台，保留连接状态
        moveTaskToBack(true);
    }

    // ---------------------------------------------------------------- 构建布局

    private void buildUi() {
        String keepLog = (logView != null) ? logView.getText().toString() : Prefs.getLastLog(this);
        String keepStatus = (status != null) ? status.getText().toString() : null;
        String keepPort = (portInput != null)
                ? portInput.getText().toString() : String.valueOf(Prefs.getPort(this));

        boolean landscape = getResources().getConfiguration().orientation
                == Configuration.ORIENTATION_LANDSCAPE;

        ScrollView panelScroll = buildPanel();
        ScrollView logPanel = buildLogPanel();

        root = new LinearLayout(this);
        root.setOrientation(landscape ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#F4F6FA"));

        if (landscape) {
            // 左：控制面板；右：日志。两边各自独立滚动。
            LinearLayout.LayoutParams lpPanel =
                    new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 0.44f);
            root.addView(panelScroll, lpPanel);

            LinearLayout.LayoutParams lpLog =
                    new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 0.56f);
            lpLog.setMargins(0, dp(10), dp(10), dp(10));
            root.addView(logPanel, lpLog);
        } else {
            // 上：控制面板（内容超出时可滚动）；下：日志占剩余空间。
            root.addView(panelScroll, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
            root.addView(logPanel, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        }

        setContentView(root);

        logView.setText(keepLog);
        if (keepStatus != null) {
            status.setText(keepStatus);
        }
        if (portInput != null && keepPort != null && keepPort.length() > 0) {
            portInput.setText(keepPort);
        }
        refreshAutoLabel();
        scrollLogToEnd();
    }

    /** 上半部分（/左侧）：标题、状态与所有按钮，整体放在 ScrollView 里。 */
    private ScrollView buildPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(14), dp(14), dp(14), dp(14));

        TextView title = new TextView(this);
        title.setText("BYD 仪表飞屏助手");
        title.setTextSize(20);
        title.setTextColor(Color.parseColor("#1A2233"));
        title.setTypeface(Typeface.DEFAULT_BOLD);
        panel.addView(title);

        TextView sub = new TextView(this);
        sub.setText("通过车机自带的 ClusterDebug 打开隐藏的仪表全屏导航（仅 18.x / 21.x 控制器）");
        sub.setTextSize(12);
        sub.setTextColor(Color.parseColor("#63708A"));
        sub.setPadding(0, dp(4), 0, dp(10));
        panel.addView(sub);

        status = new TextView(this);
        status.setTextSize(13);
        status.setTextColor(Color.parseColor("#63708A"));
        status.setText("● 未连接本地 ADB");
        status.setPadding(0, 0, 0, dp(8));
        panel.addView(status);

        // ---- ADB 端口 ----
        LinearLayout portRow = new LinearLayout(this);
        portRow.setOrientation(LinearLayout.HORIZONTAL);
        portRow.setGravity(Gravity.CENTER_VERTICAL);

        TextView portLabel = new TextView(this);
        portLabel.setText("ADB 端口");
        portLabel.setTextSize(13);
        portLabel.setTextColor(Color.parseColor("#63708A"));

        portInput = new EditText(this);
        portInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        portInput.setTextSize(13);
        portInput.setSingleLine(true);
        portInput.setText(String.valueOf(Prefs.getPort(this)));

        portRow.addView(portLabel, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        plp.leftMargin = dp(8);
        portRow.addView(portInput, plp);
        panel.addView(portRow);

        TextView portHint = new TextView(this);
        portHint.setText("车机：填 5555（BYD「无线 adb 调试」开关走明文 5555）\n"
                + "Android 11+ 手机：先电脑 USB 执行 adb tcpip 5555，否则 5555 不通");
        portHint.setTextSize(11);
        portHint.setTextColor(Color.parseColor("#8A94A6"));
        portHint.setPadding(0, 0, 0, dp(8));
        panel.addView(portHint);

        panel.addView(row(
                button("连接 / 授权", v -> doConnect()),
                button("环境自检", v -> doDiagnose())));

        panel.addView(row(
                buttonPrimary("开启仪表飞屏", v -> doEnable()),
                buttonDanger("关闭飞屏", v -> doDisable())));

        panel.addView(row(
                button("切换小屏导航", v -> doSmall()),
                autoBtn = button("开机自动开启：关", v -> toggleAuto())));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(false);
        scroll.addView(panel, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return scroll;
    }

    /** 日志区：自己就是一个可滚动的面板，负责显示执行过程。 */
    private ScrollView buildLogPanel() {
        logView = new TextView(this);
        logView.setTypeface(Typeface.MONOSPACE);
        logView.setTextSize(11);
        logView.setTextColor(Color.parseColor("#C8D6EE"));
        logView.setPadding(dp(12), dp(12), dp(12), dp(12));

        logScroll = new ScrollView(this);
        logScroll.setBackgroundColor(Color.parseColor("#0F172A"));
        logScroll.setFillViewport(true);
        logScroll.addView(logView, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return logScroll;
    }

    // ---------------------------------------------------------------- 交互

    private void doConnect() {
        final int port = currentPort();
        new Thread(() -> {
            ui.post(() -> setStatus("正在连接 127.0.0.1:" + port + " …", null));
            try {
                AdbClient c = connectWithFallback(port);
                String ver = c.shell("getprop ro.build.display.id").trim();
                ui.post(() -> {
                    setStatus("● 已连接（" + (ver.isEmpty() ? "未知固件" : ver) + "）", "#1A9E5F");
                    appendLog("已连接本地 adbd（端口 " + Prefs.getPort(this) + "）。");
                });
            } catch (Exception e) {
                ui.post(() -> {
                    setStatus("● 连接失败", "#D93B3B");
                    appendLog("连接失败：" + e.getMessage() + "\n\n" + EnvProbe.diagnose(this, port));
                });
            }
        }).start();
    }

    /** 先按界面上的端口连；失败时若探测到 adbd 实际监听的明文端口不同，自动再试一次。 */
    private AdbClient connectWithFallback(int port) throws Exception {
        try {
            return AdbManager.get(this, port, 90000);
        } catch (Exception first) {
            int alt = EnvProbe.plainTcpPort();
            if (alt > 0 && alt != port) {
                AdbManager.reset();
                try {
                    AdbClient c = AdbManager.get(this, alt, 30000);
                    Prefs.setPort(this, alt);
                    return c;
                } catch (Exception ignored) {
                    // 还是不行，抛出最初那个错误，报错信息更贴近用户的输入
                }
            }
            throw first;
        }
    }

    /** 取界面上的端口；非法或为空则回退到已保存值。 */
    private int currentPort() {
        try {
            String s = portInput == null ? "" : portInput.getText().toString().trim();
            if (!s.isEmpty()) {
                int p = Integer.parseInt(s);
                if (p > 0 && p < 65536) {
                    Prefs.setPort(this, p);
                    return p;
                }
            }
        } catch (Exception ignored) {
            // 落到下面的默认值
        }
        return Prefs.getPort(this);
    }

    private void doDiagnose() {
        run("环境自检", c -> EnvProbe.diagnose(MainActivity.this, Prefs.getPort(MainActivity.this))
                + "\n" + new ClusterController(c).diagnose());
    }

    private void doEnable() {
        run("开启仪表飞屏", c -> {
            ClusterController cc = new ClusterController(c);
            cc.enable(Prefs.getMapPackage(this));
            return cc.getLog();
        });
    }

    private void doDisable() {
        run("关闭仪表飞屏", c -> {
            ClusterController cc = new ClusterController(c);
            cc.disable();
            return cc.getLog();
        });
    }

    private void doSmall() {
        run("切换小屏导航", c -> {
            ClusterController cc = new ClusterController(c);
            cc.small();
            return cc.getLog();
        });
    }

    private interface Job {
        String run(AdbClient c) throws Exception;
    }

    private void run(String what, Job job) {
        final int port = currentPort();
        new Thread(() -> {
            ui.post(() -> setStatus("正在执行：" + what + " …", null));
            try {
                AdbClient c = connectWithFallback(port);
                String out = job.run(c);
                ui.post(() -> {
                    appendLog("▶ " + what + "\n" + out);
                    setStatus("● " + what + " 完成", "#1A9E5F");
                    Toast.makeText(this, what + " 完成", Toast.LENGTH_SHORT).show();
                });
            } catch (Exception e) {
                ui.post(() -> {
                    appendLog("▶ " + what + " 失败：" + e.getMessage()
                            + "\n\n" + EnvProbe.diagnose(this, port));
                    setStatus("● " + what + " 失败", "#D93B3B");
                });
            }
        }).start();
    }

    private void toggleAuto() {
        boolean v = !Prefs.isAutoStart(this);
        Prefs.setAutoStart(this, v);

        android.content.Intent svc = new android.content.Intent(this, FeipinService.class);
        if (v) {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                startForegroundService(svc);
            } else {
                startService(svc);
            }
        } else {
            stopService(svc);
        }

        refreshAutoLabel();
        Toast.makeText(this, v ? "已开启开机自动飞屏" : "已关闭开机自动飞屏", Toast.LENGTH_SHORT).show();
    }

    private void refreshAutoLabel() {
        if (autoBtn != null) {
            autoBtn.setText("开机自动开启：" + (Prefs.isAutoStart(this) ? "开" : "关"));
        }
    }

    // ---------------------------------------------------------------- 视图小工具

    private void setStatus(String text, String color) {
        if (status == null) return;
        status.setText(text);
        status.setTextColor(Color.parseColor(color == null ? "#63708A" : color));
    }

    private void appendLog(String text) {
        logView.append("\n\n" + text);
        Prefs.setLastLog(this, logView.getText().toString());
        scrollLogToEnd();
    }

    private void scrollLogToEnd() {
        if (logScroll != null) {
            logScroll.post(() -> logScroll.fullScroll(View.FOCUS_DOWN));
        }
    }

    private LinearLayout row(View... views) {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        for (View v : views) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0,
                    ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            lp.setMargins(dp(3), dp(3), dp(3), dp(3));
            l.addView(v, lp);
        }
        return l;
    }

    private Button button(String text, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(13);
        b.setMinHeight(dp(40));
        b.setOnClickListener(l);
        return b;
    }

    private Button buttonPrimary(String text, View.OnClickListener l) {
        Button b = button(text, l);
        b.setTextColor(Color.WHITE);
        b.setBackgroundColor(Color.parseColor("#1F6FEB"));
        return b;
    }

    private Button buttonDanger(String text, View.OnClickListener l) {
        Button b = button(text, l);
        b.setTextColor(Color.parseColor("#D93B3B"));
        return b;
    }

    private int dp(int v) {
        return Math.round(getResources().getDisplayMetrics().density * v);
    }
}
