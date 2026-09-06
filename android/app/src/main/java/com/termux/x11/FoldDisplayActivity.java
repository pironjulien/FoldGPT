package com.termux.x11;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.os.Bundle;
import android.widget.ImageView;
import androidx.appcompat.app.AlertDialog;
import androidx.core.app.NotificationCompat;

/** Host integration for the embedded display, kept outside the upstream tree.
 * Package membership deliberately permits overriding the upstream package-private
 * notification builder. @Override makes an upstream API change a build failure.
 */
public abstract class FoldDisplayActivity extends MainActivity {
    private static final String DISPLAY_CHANNEL = "foldgpt.display.v1";

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        ImageView logo = findViewById(R.id.x11_image);
        logo.setImageResource(app.foldgpt.R.drawable.foldgpt_icon);
        logo.setContentDescription(getString(app.foldgpt.R.string.foldgpt_name));
        findViewById(R.id.help_button).setOnClickListener(view ->
                new AlertDialog.Builder(this)
                        .setTitle(app.foldgpt.R.string.foldgpt_display_help_title)
                        .setMessage(app.foldgpt.R.string.foldgpt_display_help)
                        .setPositiveButton(android.R.string.ok, null)
                        .show());
    }

    @Override Notification buildNotification() {
        NotificationChannel channel = new NotificationChannel(DISPLAY_CHANNEL,
                getString(app.foldgpt.R.string.foldgpt_display_channel),
                NotificationManager.IMPORTANCE_LOW);
        channel.setLockscreenVisibility(Notification.VISIBILITY_SECRET);
        channel.setAllowBubbles(false);
        mNotificationManager.createNotificationChannel(channel);
        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, DISPLAY_CHANNEL)
                .setContentTitle(getString(app.foldgpt.R.string.foldgpt_name))
                .setContentText(getString(app.foldgpt.R.string.foldgpt_display_notification))
                .setSmallIcon(app.foldgpt.R.drawable.foldgpt_notification_icon)
                .setOngoing(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setVisibility(NotificationCompat.VISIBILITY_SECRET)
                .setSilent(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false);
        // Keep real display controls and the user's selected actions. This
        // notification says nothing about runtime health or task completion.
        return mInputHandler.setupNotification(prefs, builder).build();
    }
}
