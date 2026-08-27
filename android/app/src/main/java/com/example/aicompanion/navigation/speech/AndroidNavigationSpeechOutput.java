package com.example.aicompanion.navigation.speech;

import android.content.Context;
import android.speech.tts.TextToSpeech;

import java.util.Locale;

/** Local turn-by-turn TTS scoped to ServiceNavigationActivity. */
public final class AndroidNavigationSpeechOutput implements NavigationSpeechOutput {
    private final Object lock = new Object();
    private TextToSpeech textToSpeech;
    private String pending;
    private boolean ready;
    private boolean destroyed;

    public AndroidNavigationSpeechOutput(Context context) {
        textToSpeech = new TextToSpeech(context.getApplicationContext(), status -> {
            synchronized (lock) {
                if (destroyed || textToSpeech == null) return;
                int language = status == TextToSpeech.SUCCESS
                    ? textToSpeech.setLanguage(Locale.SIMPLIFIED_CHINESE)
                    : TextToSpeech.LANG_NOT_SUPPORTED;
                ready = status == TextToSpeech.SUCCESS
                    && language != TextToSpeech.LANG_MISSING_DATA
                    && language != TextToSpeech.LANG_NOT_SUPPORTED;
                if (ready) {
                    if (pending != null) {
                        textToSpeech.speak(pending, TextToSpeech.QUEUE_FLUSH, null, "gov-navigation");
                        pending = null;
                    }
                }
            }
        });
    }

    @Override public void speak(String text) {
        String normalized = sanitize(text);
        if (normalized.isEmpty()) return;
        synchronized (lock) {
            if (destroyed || textToSpeech == null) return;
            if (!ready) {
                pending = normalized;
                return;
            }
            textToSpeech.speak(normalized, TextToSpeech.QUEUE_FLUSH, null, "gov-navigation");
        }
    }

    @Override public void stop() {
        synchronized (lock) {
            pending = null;
            if (textToSpeech != null) textToSpeech.stop();
        }
    }

    @Override public void destroy() {
        synchronized (lock) {
            if (destroyed) return;
            destroyed = true;
            pending = null;
            if (textToSpeech != null) {
                textToSpeech.stop();
                textToSpeech.shutdown();
                textToSpeech = null;
            }
        }
    }

    private static String sanitize(String value) {
        if (value == null) return "";
        String clean = value.replaceAll("[\\r\\n\\t]", " ").trim();
        return clean.length() <= 300 ? clean : clean.substring(0, 300);
    }
}
