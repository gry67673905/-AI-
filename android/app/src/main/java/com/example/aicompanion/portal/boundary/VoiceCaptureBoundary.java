package com.example.aicompanion.portal.boundary;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;

import java.util.ArrayList;
import java.util.Locale;

/** On-device/platform speech recognition boundary. Audio is never sent to the government API. */
public final class VoiceCaptureBoundary implements RecognitionListener {
    public static final int RECORD_AUDIO_REQUEST = 3101;

    public interface Listener {
        void onState(String state);
        void onPartial(String text);
        void onFinal(String text);
        void onError(String code, String message);
    }

    private final AppCompatActivity activity;
    private final Listener listener;
    private SpeechRecognizer recognizer;
    private boolean pendingPermissionStart;

    public VoiceCaptureBoundary(AppCompatActivity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
    }

    public void start() {
        if (ActivityCompat.checkSelfPermission(activity, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            pendingPermissionStart = true;
            ActivityCompat.requestPermissions(activity, new String[]{Manifest.permission.RECORD_AUDIO}, RECORD_AUDIO_REQUEST);
            return;
        }
        pendingPermissionStart = false;
        if (!SpeechRecognizer.isRecognitionAvailable(activity)) {
            listener.onError("speech_unavailable", "设备没有可用的语音识别服务");
            return;
        }
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(activity);
            recognizer.setRecognitionListener(this);
        } else {
            recognizer.cancel();
        }
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.SIMPLIFIED_CHINESE.toLanguageTag())
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3);
        recognizer.startListening(intent);
        listener.onState("listening");
    }

    public void stop() {
        pendingPermissionStart = false;
        if (recognizer != null) recognizer.stopListening();
        listener.onState("processing");
    }

    public void onPermissionResult(boolean granted) {
        if (granted && pendingPermissionStart) start();
        else if (!granted) listener.onError("microphone_permission_denied", "未授予麦克风权限");
        pendingPermissionStart = false;
    }

    public void destroy() {
        pendingPermissionStart = false;
        if (recognizer != null) {
            recognizer.cancel();
            recognizer.destroy();
            recognizer = null;
        }
    }

    @Override public void onReadyForSpeech(Bundle params) { listener.onState("ready"); }
    @Override public void onBeginningOfSpeech() { listener.onState("speaking"); }
    @Override public void onRmsChanged(float rmsdB) {}
    @Override public void onBufferReceived(byte[] buffer) {}
    @Override public void onEndOfSpeech() { listener.onState("processing"); }

    @Override
    public void onError(int error) {
        listener.onError("speech_recognition_error", describeError(error));
    }

    @Override
    public void onResults(Bundle results) {
        String text = first(results);
        if (text.isEmpty()) listener.onError("empty_speech", "未识别到有效内容");
        else listener.onFinal(text);
    }

    @Override public void onPartialResults(Bundle partialResults) {
        String text = first(partialResults);
        if (!text.isEmpty()) listener.onPartial(text);
    }
    @Override public void onEvent(int eventType, Bundle params) {}

    private static String first(Bundle bundle) {
        if (bundle == null) return "";
        ArrayList<String> values = bundle.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
        return values == null || values.isEmpty() || values.get(0) == null ? "" : values.get(0).trim();
    }

    private static String describeError(int error) {
        switch (error) {
            case SpeechRecognizer.ERROR_AUDIO: return "录音出现错误";
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS: return "麦克风权限不足";
            case SpeechRecognizer.ERROR_NETWORK:
            case SpeechRecognizer.ERROR_NETWORK_TIMEOUT: return "语音识别网络不可用";
            case SpeechRecognizer.ERROR_NO_MATCH: return "没有识别到匹配内容";
            case SpeechRecognizer.ERROR_RECOGNIZER_BUSY: return "语音识别器正忙";
            case SpeechRecognizer.ERROR_SPEECH_TIMEOUT: return "等待语音输入超时";
            default: return "语音识别失败（" + error + "）";
        }
    }
}
