package com.wb.bydfeipin;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * 后台常驻服务：开机后自动连接本地 adbd 并打开仪表飞屏，之后定期自检。
 *
 * <p>它只做一件事——保证「全屏导航」这个隐藏开关一直处于打开状态。
 */
public class FeipinService extends Service {

    private static final String CHANNEL_ID = "bydfeipin";
    private static final int NOTI_ID = 1001;

    private volatile boolean running = false;
    private Thread worker;

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTI_ID, buildNotification("正在守护仪表飞屏"));
        if (!running) {
            running = true;
            worker = new Thread(this::loop, "feipin-worker");
            worker.setDaemon(true);
            worker.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        if (worker != null) worker.interrupt();
        super.onDestroy();
    }

    private void loop() {
        int attempt = 0;
        while (running) {
            if (!Prefs.isAutoStart(this)) {
                sleep(60000);
                continue;
            }
            try {
                AdbClient c = AdbManager.get(this, 90000);
                ClusterController cc = new ClusterController(c);
                int type = cc.readNaviType();
                if (type != 4) {
                    cc.enable(Prefs.getMapPackage(this));
                    Prefs.setLastLog(this, "[自动] " + cc.getLog());
                }
                attempt = 0;
                sleep(5 * 60 * 1000);        // 每 5 分钟巡检一次
            } catch (Exception e) {
                attempt++;
                String extra = attempt == 1
                        ? "\n\n" + EnvProbe.diagnose(this, Prefs.getPort(this)) : "";
                Prefs.setLastLog(this, "[自动] 第 " + attempt + " 次连接失败：" + e.getMessage() + extra);
                AdbManager.reset();
                sleep(Math.min(15000L * attempt, 120000L));
            }
        }
    }

    private void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }

    // ---- 通知 ----

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (nm != null && nm.getNotificationChannel(CHANNEL_ID) == null) {
                NotificationChannel ch = new NotificationChannel(
                        CHANNEL_ID, "仪表飞屏守护", NotificationManager.IMPORTANCE_LOW);
                ch.setDescription("后台维持仪表全屏导航");
                nm.createNotificationChannel(ch);
            }
        }
    }

    private Notification buildNotification(String text) {
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            b = new Notification.Builder(this, CHANNEL_ID);
        } else {
            b = new Notification.Builder(this);
        }
        b.setContentTitle("BYD 仪表飞屏助手")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setOngoing(true);
        return b.build();
    }
}
