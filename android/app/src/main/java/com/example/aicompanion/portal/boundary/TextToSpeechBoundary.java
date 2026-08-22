package com.example.aicompanion.portal.boundary;

import android.content.Context;
import android.speech.tts.TextToSpeech;

import java.util.Locale;

/** Native speech output; only final assistant text is spoken. */
public final class TextToSpeechBoundary implements TextToSpeech.OnInitListener {
    private final TextToSpeech engine;
    private boolean ready;
    private boolean destroyed;
    private String pendingText = "";

    public TextToSpeechBoundary(Context context) {
        engine = new TextToSpeech(context.getApplicationContext(), this);
    }

    @Override
    public void onInit(int status) {
        if (destroyed) return;
        int language = status == TextToSpeech.SUCCESS
            ? engine.setLanguage(Locale.SIMPLIFIED_CHINESE) : TextToSpeech.LANG_NOT_SUPPORTED;
        ready = status == TextToSpeech.SUCCESS
            && language != TextToSpeech.LANG_MISSING_DATA
            && language != TextToSpeech.LANG_NOT_SUPPORTED;
        if (ready && !pendingText.isEmpty()) {
            String value = pendingText;
            pendingText = "";
            speak(value);
        }
    }

    public void speak(String rawText) {
        if (destroyed) return;
        String text = rawText == null ? "" : rawText.trim();
        if (text.isEmpty()) return;
        if (text.length() > 4000) text = text.substring(0, 4000);
        if (!ready) {
            pendingText = text;
            return;
        }
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "gov-assistant-answer");
    }

    public void stop() { if (!destroyed) engine.stop(); }
    public void destroy() { destroyed = true; engine.stop(); engine.shutdown(); ready = false; pendingText = ""; }
}
