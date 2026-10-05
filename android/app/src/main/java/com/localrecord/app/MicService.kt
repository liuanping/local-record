package com.localrecord.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon
import android.os.Build
import android.os.IBinder
import android.util.Log

/**
 * 录音期间的前台服务（`foregroundServiceType=microphone`）。
 *
 * **为什么必须有它**：Android 9 起，后台应用**不能访问麦克风** ——
 * 切到别的 app（或锁屏）约 30 秒后，AudioRecord 就再也拿不到数据，
 * 表现就是"录着录着不出字了"，而且不报错。声明了 microphone 类型的前台服务，
 * 系统才允许在后台继续录音，同时进程不会被低内存杀手干掉。
 *
 * 通知栏显示录音时长与已出段数，并带一个「停止录音」按钮（不需要回到 app 就能停）。
 */
class MicService : Service() {

    companion object {
        private const val TAG = "MicService"
        private const val CHANNEL_ID = "localrecord-mic"
        private const val NOTIF_ID = 1002
        const val ACTION_STOP = "com.localrecord.app.STOP_RECORDING"

        @Volatile var active = false
            private set

        /** 进度由 Activity 的计时器写、服务读（同进程） */
        @Volatile var elapsedText: String = "00:00.0"
        @Volatile var segText: String = "已出 0 段"

        fun start(ctx: Context) {
            try {
                val i = Intent(ctx, MicService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    ctx.startForegroundService(i)
                } else {
                    ctx.startService(i)
                }
                Log.i(TAG, "麦克风前台服务已启动（后台也能继续录音）")
            } catch (e: Throwable) {
                Log.w(TAG, "启动麦克风前台服务失败（可能导致后台录音中断）：${e.message}")
            }
        }

        fun stop(ctx: Context) {
            try {
                ctx.stopService(Intent(ctx, MicService::class.java))
                Log.i(TAG, "麦克风前台服务已停止")
            } catch (_: Throwable) {
            }
        }
    }

    private var ticker: Thread? = null
    private var nm: NotificationManager? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm?.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "录音", NotificationManager.IMPORTANCE_LOW)
            )
        }
        try {
            startForeground(NOTIF_ID, buildNotification())
        } catch (e: Throwable) {
            // Android 14+ 要求启动时已授予麦克风权限；没授权就只记日志（录音本来也不能用）
            Log.w(TAG, "startForeground(microphone) 失败：${e.message}")
        }
        active = true
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
        }, "mic-notif").also { it.start() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onDestroy() {
        active = false
        ticker?.interrupt()
        ticker = null
        super.onDestroy()
    }

    private fun buildNotification(): Notification {
        val openApp = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stopIntent = PendingIntent.getBroadcast(
            this, 1,
            Intent(ACTION_STOP).setPackage(packageName),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val b = Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("正在录音 $elapsedText")
            .setContentText("$segText · 后台继续录音中")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(openApp)
            .addAction(
                Notification.Action.Builder(
                    Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                    "停止录音", stopIntent
                ).build()
            )
            .setOngoing(true)
            .setOnlyAlertOnce(true)
        return b.build()
    }
}

/** 通知栏「停止录音」按钮 → 广播到这里（不用回到 app 就能停） */
class StopRecordReceiver : android.content.BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != MicService.ACTION_STOP) return
        android.util.Log.i("StopRecordReceiver", "收到通知栏停止录音")
        MainActivity.stopRequested = true          // Activity 的计时器会看到并收尾
        MicService.stop(context)
    }
}
