package com.openai.chatgpt.launcher;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        try {
            Intent x11Intent = new Intent();
            x11Intent.setClassName("com.termux.x11", "com.termux.x11.MainActivity");
            x11Intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            startActivity(x11Intent);
        } catch (Exception e) {}

        finish();
    }
}
