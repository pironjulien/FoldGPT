package app.foldgpt;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** OS permission status and shortcuts. There is no second application permission switch. */
public final class AndroidToolsActivity extends androidx.appcompat.app.AppCompatActivity {
    private static volatile boolean visible;
    public static boolean isVisible() { return visible; }
    private LinearLayout content;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        FoldAndroidBridge.start(this);
    }
    @Override public void onResume() { super.onResume(); visible = true; render(); }
    @Override public void onPause() { visible = false; super.onPause(); }
    private void render() {
        ScrollView scroll = new ScrollView(this);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() | android.view.WindowInsets.Type.displayCutout());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        content.setId(R.id.android_tools_consent);
        int pad = (int)(24 * getResources().getDisplayMetrics().density); content.setPadding(pad,pad,pad,pad);
        scroll.addView(content); setContentView(scroll);
        text("Outils Android", 25);
        text("Demandez à ChatGPT de chercher un message ou d’utiliser une application. Android vous demandera l’accès nécessaire au moment de l’utiliser.", 17);
        text("Les messages et captures consultés à votre demande sont transmis au modèle dans votre conversation. Ces accès restent révocables dans les paramètres Android.", 16);
        boolean screen = FoldAndroidPermissionActivity.isGranted(this, "screen_control");
        boolean connected = FoldAccessibilityService.isConnected();
        text("Applications à l’écran : " + (screen
                ? "accès autorisé · service " + (connected ? "connecté" : "déconnecté")
                : "accès non autorisé"), 18);
        if (screen && !connected)
            text("Android a conservé l’autorisation, mais le service n’est pas connecté. Les paramètres d’accessibilité permettent de vérifier son état.", 16);
        button(screen ? "Gérer l’accès à l’écran" : "Autoriser l’accès à l’écran", () -> {
            if (screen) FoldAndroidPermissionActivity.openAccessibilitySettings(this);
            else showRequest("screen_control");
        });
        text("SMS : lecture " + granted(Manifest.permission.READ_SMS) + " · envoi " + granted(Manifest.permission.SEND_SMS), 18);
        if (checkSelfPermission(Manifest.permission.READ_SMS) != PackageManager.PERMISSION_GRANTED)
            button("Autoriser la recherche de SMS", () -> showRequest("sms_read"));
        text("L’autorisation d’envoi sera proposée si vous demandez d’envoyer un message. Les archives, le RCS et le rangement passent par Google Messages.", 16);
        button("Gérer les autorisations Android", () -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                .setData(Uri.parse("package:" + getPackageName()))));
        button("Retour à ChatGPT", () -> { startActivity(new Intent(this, FoldActivity.class)); finish(); });
    }
    private String granted(String name) {
        String state = Manifest.permission.SEND_SMS.equals(name) ? "autorisé" : "autorisée";
        return (checkSelfPermission(name) == PackageManager.PERMISSION_GRANTED ? "" : "non ") + state;
    }
    private void text(String value, int size) { TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setPadding(0,12,0,12); content.addView(view); }
    private void button(String label, Runnable action) { Button button = new Button(this); button.setText(label); button.setOnClickListener(view -> action.run()); content.addView(button); }
    private void showRequest(String scope) {
        org.json.JSONObject response = FoldAndroidPermissionActivity.requestFromPanel(this, scope);
        if (!response.optBoolean("ok")) {
            String message = "permission_denied".equals(response.optString("error"))
                    ? "Accès refusé. Vous pouvez le modifier dans les autorisations Android."
                    : "Android n’a pas pu ouvrir cette demande. Réessayez depuis cet écran.";
            android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show();
        }
    }
}
