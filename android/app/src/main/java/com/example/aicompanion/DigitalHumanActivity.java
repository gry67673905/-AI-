package com.example.aicompanion;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.PermissionRequest;
import android.webkit.WebView;
import android.widget.ProgressBar;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.example.aicompanion.metastudio.boundary.DigitalHumanWebViewClient;
import com.example.aicompanion.metastudio.boundary.DigitalHumanWebViewHost;
import com.example.aicompanion.metastudio.business.DigitalHumanAvailability;
import com.example.aicompanion.metastudio.business.DigitalHumanMessagePolicy;
import com.example.aicompanion.metastudio.business.DigitalHumanNetworkPolicy;
import com.example.aicompanion.metastudio.business.DigitalHumanSdkDiagnostics;
import com.example.aicompanion.metastudio.coordinator.DigitalHumanCoordinator;
import com.example.aicompanion.metastudio.gateway.OkHttpDigitalHumanGateway;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.NavigationIntent;
import com.example.aicompanion.portal.gateway.AndroidKeystoreSessionStore;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.SecureSessionStore;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.google.gson.Gson;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Isolated MetaStudio host. It has no GovPortalNative bridge and never exposes a JWT, AK/SK,
 * TokenStore, arbitrary URL, local speech recognizer, or native TTS to page JavaScript.
 */
public final class DigitalHumanActivity extends AppCompatActivity {
    public static final String EXTRA_NAVIGATION_JSON = "digital_human_navigation_json";
    private static final int AUDIO_PERMISSION_REQUEST = 7401;
    private static final AtomicBoolean WEBVIEW_DIRECTORY_CONFIGURED = new AtomicBoolean();

    private final Gson gson = new Gson();
    private final DigitalHumanMessagePolicy messagePolicy = new DigitalHumanMessagePolicy();
    private final AtomicBoolean sessionRequested = new AtomicBoolean();

    private WebView webView;
    private TextView status;
    private ProgressBar progress;
    private DigitalHumanCoordinator coordinator;
    private NativeApiClient api;
    private PermissionRequest pendingAudioPermission;
    private boolean destroyed;
    private boolean foreground;
    private boolean sessionTerminated;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        // The isolated process must use its own WebView data directory before inflation.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P
            && WEBVIEW_DIRECTORY_CONFIGURED.compareAndSet(false, true)) {
            WebView.setDataDirectorySuffix("digital_human");
        }
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_digital_human);

        webView = findViewById(R.id.digitalHumanWebView);
        status = findViewById(R.id.digitalHumanStatus);
        progress = findViewById(R.id.digitalHumanProgress);
        findViewById(R.id.digitalHumanClose).setOnClickListener(view -> finish());

        DigitalHumanAvailability.Decision availability = new DigitalHumanAvailability().check(this);
        if (!availability.isAvailable()) {
            showFatal(availability.getMessage());
            return;
        }
        if (!DigitalHumanWebViewHost.isMessagingSupported()) {
            showFatal("当前 Android System WebView 不支持安全的数字人消息通道");
            return;
        }

        AndroidKeystoreSessionStore sessionStore = new AndroidKeystoreSessionStore(getApplicationContext());
        SecureSessionStore.Snapshot snapshot = sessionStore.load();
        api = new NativeApiClient(NativeApiClient.defaultClient(), BuildConfig.GOV_API_BASE, sessionStore);
        coordinator = new DigitalHumanCoordinator(
            new OkHttpDigitalHumanGateway(api),
            snapshot.getProfile().getRole()
        );

        try {
            DigitalHumanWebViewHost.configure(
                this,
                webView,
                this::onWrapperMessage,
                audioPermissionDelegate(),
                pageListener()
            );
            webView.loadUrl(DigitalHumanNetworkPolicy.START_URL);
        } catch (RuntimeException unsupported) {
            showFatal("当前设备无法建立安全的数字人页面");
        }
    }

    private void onWrapperMessage(String raw, DigitalHumanWebViewHost.ReplyChannel reply) {
        DigitalHumanMessagePolicy.Decision decision = messagePolicy.validate(raw);
        if (!decision.isAllowed()) {
            showStatus(decision.getMessage(), false);
            return;
        }
        switch (decision.getEvent()) {
            case "page_ready":
                requestClientSession(reply);
                return;
            case "close":
                finish();
                return;
            case "sdk_status":
                onSdkStatus(decision.getStatus());
                return;
            case "semantic_final":
                exchangeIntent(decision);
                return;
            default:
                showStatus("收到不受支持的数字人页面事件", false);
        }
    }

    private void requestClientSession(DigitalHumanWebViewHost.ReplyChannel reply) {
        if (coordinator == null || !sessionRequested.compareAndSet(false, true)) return;
        showStatus("正在申请一次性数字人会话…", true);
        coordinator.createSession(new GatewayCallback<ClientSession>() {
            @Override public void onSuccess(ClientSession value) {
                runOnUiThread(() -> {
                    if (destroyed || sessionTerminated || !foreground || webView == null) return;
                    reply.post(gson.toJson(value.toWebMessage()));
                    showStatus("正在连接华为云 MetaStudio…", true);
                });
            }

            @Override public void onError(ApiFailure error) {
                runOnUiThread(() -> {
                    sessionRequested.set(false);
                    showFatal(error == null ? "无法创建数字人会话" : error.getMessage());
                });
            }
        });
    }

    private void exchangeIntent(DigitalHumanMessagePolicy.Decision decision) {
        if (coordinator == null || decision.getSemanticIntent() == null) return;
        showStatus("正在准备安全操作建议…", true);
        coordinator.exchange(decision.getSemanticIntent(), new DigitalHumanCoordinator.ExchangeCallback() {
            @Override public void onSuccess(NavigationIntent intent) {
                runOnUiThread(() -> finishWithIntent(intent));
            }

            @Override public void onDuplicate() {
                runOnUiThread(() -> showStatus("已忽略重复的语义结果", false));
            }

            @Override public void onError(ApiFailure error) {
                runOnUiThread(() -> showStatus(
                    error == null ? "无法交换数字人操作建议" : error.getMessage(), false
                ));
            }
        });
    }

    private void finishWithIntent(NavigationIntent navigationIntent) {
        if (destroyed || navigationIntent == null) return;
        Intent result = new Intent();
        result.putExtra(EXTRA_NAVIGATION_JSON, gson.toJson(navigationIntent.toPortalEvent()));
        setResult(RESULT_OK, result);
        finish();
    }

    private void onSdkStatus(String sdkStatus) {
        String diagnostic = DigitalHumanSdkDiagnostics.friendlyMessage(sdkStatus);
        if (diagnostic != null) {
            showStatus(diagnostic, false);
            return;
        }
        switch (sdkStatus) {
            case "checking_browser": showStatus("正在检查 System WebView 兼容性…", true); break;
            case "creating": showStatus("正在创建数字人交互任务…", true); break;
            case "ready": showStatus("数字人已就绪，请点击页面中的开始对话", false); break;
            case "active": showStatus("数字人正在聆听", false); break;
            case "ended": showStatus("本次数字人会话已结束", false); break;
            case "unsupported": showFatal("当前 Android System WebView 未通过 MetaStudio checkBrowserSupport"); break;
            case "sdk_missing": showFatal("MetaStudio Web SDK 未正确加载"); break;
            case "error": showStatus("数字人交互暂时不可用", false); break;
            default: showStatus("数字人状态已更新", false);
        }
    }

    private DigitalHumanWebViewClient.Listener pageListener() {
        return new DigitalHumanWebViewClient.Listener() {
            @Override public void onPageReady() { showStatus("数字人安全页面已加载", true); }
            @Override public void onBlocked(String code, String message) { showStatus(message, false); }
            @Override public void onRendererGone(WebView deadView, String message) {
                showStatus(message, false);
                sessionTerminated = true;
                foreground = false;
                if (api != null) api.cancelAll();
                PermissionRequest request = pendingAudioPermission;
                pendingAudioPermission = null;
                if (request != null) request.deny();
                if (deadView != null) {
                    if (deadView.getParent() instanceof ViewGroup) {
                        ((ViewGroup) deadView.getParent()).removeView(deadView);
                    }
                    if (deadView == webView) webView = null;
                    // Android requires destroy after renderer death, but no
                    // load/clear/navigation calls on the unusable instance.
                    deadView.destroy();
                }
                finish();
            }
        };
    }

    private DigitalHumanWebViewHost.AudioPermissionDelegate audioPermissionDelegate() {
        return new DigitalHumanWebViewHost.AudioPermissionDelegate() {
            @Override public void request(PermissionRequest request) {
                runOnUiThread(() -> requestAudioPermission(request));
            }

            @Override public void cancelled(PermissionRequest request) {
                runOnUiThread(() -> {
                    if (pendingAudioPermission == request) pendingAudioPermission = null;
                });
            }
        };
    }

    private void requestAudioPermission(PermissionRequest request) {
        if (destroyed || request == null) return;
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED) {
            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            return;
        }
        if (pendingAudioPermission != null && pendingAudioPermission != request) {
            pendingAudioPermission.deny();
        }
        pendingAudioPermission = request;
        ActivityCompat.requestPermissions(
            this,
            new String[]{Manifest.permission.RECORD_AUDIO},
            AUDIO_PERMISSION_REQUEST
        );
    }

    @Override
    public void onRequestPermissionsResult(
        int requestCode,
        @NonNull String[] permissions,
        @NonNull int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != AUDIO_PERMISSION_REQUEST) return;
        PermissionRequest request = pendingAudioPermission;
        pendingAudioPermission = null;
        if (request == null) return;
        if (grantResults.length == 1 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
        } else {
            request.deny();
            showStatus("未授予麦克风权限，无法使用 SIS 语音交互", false);
        }
    }

    private void showStatus(String message, boolean busy) {
        if (destroyed || status == null || progress == null) return;
        status.setText(message == null || message.trim().isEmpty() ? "数字人状态已更新" : message);
        progress.setVisibility(busy ? View.VISIBLE : View.GONE);
    }

    private void showFatal(String message) {
        showStatus(message, false);
        if (webView != null) webView.setVisibility(View.INVISIBLE);
    }

    @Override
    protected void onResume() {
        super.onResume();
        foreground = true;
        if (webView != null) webView.onResume();
    }

    @Override
    protected void onPause() {
        foreground = false;
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override
    protected void onStop() {
        // onceCode is single-use and the SDK may retain a live WebRTC audio
        // track. Leaving the Activity therefore terminates the session; a
        // return always starts a new Activity and obtains a fresh onceCode.
        terminateSession();
        super.onStop();
        if (!isFinishing()) finish();
    }

    private void terminateSession() {
        if (sessionTerminated) return;
        sessionTerminated = true;
        PermissionRequest request = pendingAudioPermission;
        pendingAudioPermission = null;
        if (request != null) request.deny();
        if (api != null) api.cancelAll();
        DigitalHumanWebViewHost.destroy(webView);
        webView = null;
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        terminateSession();
        super.onDestroy();
    }
}
