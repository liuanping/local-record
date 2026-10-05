package com.localrecord.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * 模型下载期间的前台服务。
 *
 * 为什么需要它：下载 2GB 要好几分钟，用户一定会切到别的 app。
 * 普通 Activity 里的线程在后台会被系统冻结/杀掉，下载就断了。
 * 起一个前台服务（带进度通知）能保证：
 *  * 进程不被杀，下载继续跑；
 *  * 通知栏和锁屏上能看到进度；
 *  * 用户切回来时，进度条接着显示（进度通过下面这些静态字段共享）。
 */
class DownloadService : Service() {

    companion object {
        private const val TAG = "DownloadService"
        private const val CHANNEL_ID = "localrecord-download"
        private const val NOTIF_ID = 1001

        @Volatile var active = false
            private set

        /** 进度由 Activity 写、服务读（同进程，够用） */
        @Volatile var title: String = "正在下载模型"
        @Volatile var detail: String = ""
        @Volatile var percent: Int = -1

        fun start(ctx: Context) {
            try {
                val i = Intent(ctx, DownloadService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    ctx.startForegroundService(i)
                } else {
                    ctx.startService(i)
                }
                Log.i(TAG, "前台下载服务已启动")
            } catch (e: Throwable) {
                Log.w(TAG, "启动前台服务失败（不影响下载）：${e.message}")
            }
        }

        fun stop(ctx: Context) {
            try {
                ctx.stopService(Intent(ctx, DownloadService::class.java))
                Log.i(TAG, "前台下载服务已停止")
            } catch (_: Throwable) {
            }
        }
    }

    private var ticker: Thread? = null
    private var nm: NotificationManager? = null
    private var wakeLock: android.os.PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm?.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "模型下载", NotificationManager.IMPORTANCE_LOW)
            )
        }
        try {
            startForeground(NOTIF_ID, buildNotification())
        } catch (e: Throwable) {
            Log.w(TAG, "startForeground 失败：${e.message}")
        }
        active = true
        // 锁屏/息屏也继续下（wakelock 由服务持有，用户切走或锁屏都不会断）
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as android.os.PowerManager
            wakeLock = pm.newWakeLock(
                android.os.PowerManager.PARTIAL_WAKE_LOCK, "LocalRecord:download"
            ).apply { acquire(60 * 60 * 1000L) }
        } catch (e: Throwable) {
            Log.w(TAG, "拿 wakelock 失败：${e.message}")
        }
        ticker = Thread({
            while (active) {
                try {
                    nm?.notify(NOTIF_ID, buildNotification())
                } catch (_: Throwable) {
                }
                try {
                    Thread.sleep(1000)
                } catch (_: InterruptedException) {
                    break
                }
            }
        }, "download-notif").also { it.start() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        active = false
        ticker?.interrupt()
        ticker = null
        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (_: Throwable) {
        }
        wakeLock = null
        super.onDestroy()
    }

    private fun buildNotification(): Notification {
        val b = Notification.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(detail)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
        if (percent in 0..100) b.setProgress(100, percent, false) else b.setProgress(0, 0, true)
        return b.build()
    }
}
