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
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.appcompat.app.AlertDialog;
import androidx.camera.view.PreviewView;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.example.aicompanion.metastudio.boundary.DigitalHumanWebViewClient;
import com.example.aicompanion.metastudio.boundary.DigitalHumanWebViewHost;
import com.example.aicompanion.metastudio.business.DigitalHumanAvailability;
import com.example.aicompanion.metastudio.business.DigitalHumanMessagePolicy;
import com.example.aicompanion.metastudio.business.DigitalHumanNetworkPolicy;
import com.example.aicompanion.metastudio.business.DigitalHumanSdkDiagnostics;
import com.example.aicompanion.metastudio.business.VisionSessionPolicy;
import com.example.aicompanion.metastudio.coordinator.DigitalHumanCoordinator;
import com.example.aicompanion.metastudio.gateway.OkHttpDigitalHumanGateway;
import com.example.aicompanion.metastudio.gateway.OkHttpVisionSessionGateway;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.NavigationIntent;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.VisionSession;
import com.example.aicompanion.metastudio.vision.CameraXVisionController;
import com.example.aicompanion.metastudio.vision.VisionWebSocketGateway;
import com.example.aicompanion.portal.gateway.BrokeredSecureSessionStore;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.OkHttpAuthGateway;
import com.example.aicompanion.portal.gateway.SecureSessionStore;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.Gson;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Isolated MetaStudio host. It has no GovPortalNative bridge and never exposes a JWT, AK/SK,
 * TokenStore, arbitrary URL, local speech recognizer, or native TTS to page JavaScript.
 */
public final class DigitalHumanActivity extends AppCompatActivity {
    public static final String EXTRA_NAVIGATION_JSON = "digital_human_navigation_json";
    private static final int AUDIO_PERMISSION_REQUEST = 7401;
    private static final String VISION_PREFS = "digital_human_vision";
    private static final String VISION_NOTICE_ACCEPTED = "camera_notice_accepted";
    private static final AtomicBoolean WEBVIEW_DIRECTORY_CONFIGURED = new AtomicBoolean();

    private final Gson gson = new Gson();
    private final DigitalHumanMessagePolicy messagePolicy = new DigitalHumanMessagePolicy();
    private final AtomicBoolean sessionRequested = new AtomicBoolean();
    private final VisionSessionPolicy visionSessionPolicy = new VisionSessionPolicy();
    private final ActivityResultLauncher<String> cameraPermissionLauncher = registerForActivityResult(
        new ActivityResultContracts.RequestPermission(),
        this::onCameraPermissionResult
    );

    private WebView webView;
    private TextView status;
    private ProgressBar progress;
    private Button visionToggle;
    private Button cameraSwitch;
    private Button documentRecognize;
    private Button documentCapture;
    private Button documentCancel;
    private PreviewView visionPreview;
    private View visionPreviewContainer;
    private View documentOverlay;
    private ViewGroup.LayoutParams compactPreviewLayoutParams;
    private DigitalHumanCoordinator coordinator;
    private NativeApiClient api;
    private OkHttpAuthGateway authGateway;
    private OkHttpVisionSessionGateway visionSessionGateway;
    private VisionWebSocketGateway visionWebSocketGateway;
    private CameraXVisionController visionController;
    private PermissionRequest pendingAudioPermission;
    private Role role = Role.ANONYMOUS;
    private String visionClientSessionId = "";
    private boolean visionTicketRequestInFlight;
    private boolean cameraAvailable;
    private boolean cameraCanSwitch;
    private boolean cameraPermissionInFlight;
    private boolean cameraEnableQueued;
    // Document capture is a separate protocol state and may only start while
    // MetaStudio is idle/listening.  Keeping the button enabled during ASR or
    // digital-human speech lets a valid user tap race an unfinished visual
    // turn and previously produced a misleading "vision channel" failure.
    private boolean documentInteractionBusy = true;
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
        visionToggle = findViewById(R.id.digitalHumanVisionToggle);
        cameraSwitch = findViewById(R.id.digitalHumanCameraSwitch);
        documentRecognize = findViewById(R.id.digitalHumanDocumentRecognize);
        documentCapture = findViewById(R.id.digitalHumanDocumentCapture);
        documentCancel = findViewById(R.id.digitalHumanDocumentCancel);
        visionPreview = findViewById(R.id.digitalHumanVisionPreview);
        visionPreviewContainer = findViewById(R.id.digitalHumanVisionPreviewContainer);
        documentOverlay = findViewById(R.id.digitalHumanDocumentOverlay);
        compactPreviewLayoutParams = visionPreviewContainer.getLayoutParams();
        findViewById(R.id.digitalHumanClose).setOnClickListener(view -> finish());
        visionToggle.setVisibility(View.GONE);
        cameraSwitch.setVisibility(View.GONE);
        documentRecognize.setVisibility(View.GONE);
        documentOverlay.setVisibility(View.GONE);
        visionPreview.setVisibility(View.GONE);
        visionToggle.setOnClickListener(view -> toggleVision());
        cameraSwitch.setOnClickListener(view -> {
            if (visionController != null) visionController.switchCamera();
        });
        documentRecognize.setOnClickListener(view -> enterDocumentMode());
        documentCapture.setOnClickListener(view -> captureDocument());
        documentCancel.setOnClickListener(view -> cancelDocumentMode());

        DigitalHumanAvailability.Decision availability = new DigitalHumanAvailability().check(this);
        if (!availability.isAvailable()) {
            showFatal(availability.getMessage());
            return;
        }
        if (!DigitalHumanWebViewHost.isMessagingSupported()) {
            showFatal("当前 Android System WebView 不支持安全的数字人消息通道");
            return;
        }

        SecureSessionStore sessionStore = new BrokeredSecureSessionStore(getApplicationContext());
        api = new NativeApiClient(NativeApiClient.defaultClient(), BuildConfig.GOV_API_BASE, sessionStore);
        authGateway = new OkHttpAuthGateway(api);
        showStatus("正在恢复安全登录状态…", true);
        restoreSessionAndInitialize();
    }

    private void restoreSessionAndInitialize() {
        try {
            authGateway.restore(new GatewayCallback<UserProfile>() {
                @Override public void onSuccess(UserProfile profile) {
                    runOnUiThread(() -> initializeDigitalHuman(profile));
                }

                @Override public void onError(ApiFailure error) {
                    runOnUiThread(() -> showFatal("无法恢复数字人登录状态"));
                }
            });
        } catch (RuntimeException unavailable) {
            showFatal("无法读取安全登录状态，请返回工作台重试");
        }
    }

    private void initializeDigitalHuman(UserProfile profile) {
        if (destroyed || sessionTerminated) return;
        role = profile == null ? Role.ANONYMOUS : profile.getRole();
        coordinator = new DigitalHumanCoordinator(new OkHttpDigitalHumanGateway(api), role);
        configureVisionForRole();

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

    private void configureVisionForRole() {
        if (role == Role.ANONYMOUS) {
            visionToggle.setVisibility(View.GONE);
            cameraSwitch.setVisibility(View.GONE);
            documentRecognize.setVisibility(View.GONE);
            return;
        }
        visionToggle.setVisibility(View.VISIBLE);
        visionToggle.setEnabled(false);
        visionSessionGateway = new OkHttpVisionSessionGateway(api);
        visionWebSocketGateway = new VisionWebSocketGateway(
            BuildConfig.GOV_API_BASE,
            new VisionWebSocketGateway.Listener() {
                @Override public void onConnected() {
                    runOnUiThread(() -> {
                        if (!destroyed) showStatus("视觉辅助已就绪", false);
                    });
                }

                @Override public void onFrameAcknowledged(
                    long turnSeq, long frameSeq, String status
                ) {
                    runOnUiThread(() -> {
                        if (!destroyed) showStatus("视觉关键帧已确认", false);
                    });
                }

                @Override public void onTurnEnded(long turnSeq) {
                    runOnUiThread(() -> {
                        if (!destroyed) showStatus("本轮视觉帧已提交，正在融合回答…", true);
                    });
                }

                @Override public void onDocumentStarted(long documentSeq) {
                    runOnUiThread(() -> {
                        if (destroyed || visionController == null) return;
                        visionController.onDocumentStarted(documentSeq);
                        showStatus("文件照片正在上传…", true);
                    });
                }

                @Override public void onDocumentAcknowledged(
                    long documentSeq, String receiptStatus
                ) {
                    runOnUiThread(() -> {
                        if (destroyed) return;
                        showStatus("正在识别文件内容…", true);
                    });
                }

                @Override public void onDocumentReady(long documentSeq) {
                    runOnUiThread(() -> {
                        if (destroyed || visionController == null) return;
                        visionController.onDocumentReady(documentSeq);
                        showStatus("已看清，可以继续提问", false);
                    });
                }

                @Override public void onDocumentFailed(long documentSeq, String message) {
                    runOnUiThread(() -> {
                        if (destroyed || visionController == null) return;
                        visionController.onDocumentFailed(documentSeq);
                        showStatus(
                            message == null ? "本次文件识别未完成，普通视觉仍可继续" : message,
                            false
                        );
                    });
                }

                @Override public void onDisconnected() {
                    runOnUiThread(() -> {
                        if (!destroyed && visionController != null && visionController.isEnabled()) {
                            visionController.disable();
                            showStatus("视觉辅助连接已关闭，语音对话仍可继续", false);
                        }
                    });
                }

                @Override public void onError(String message) {
                    runOnUiThread(() -> {
                        if (destroyed) return;
                        if (visionController != null && visionController.isEnabled()) {
                            visionController.disable();
                        }
                        showStatus(message == null ? "视觉辅助暂时不可用" : message, false);
                    });
                }
            }
        );
        visionController = new CameraXVisionController(
            this,
            visionPreview,
            visionWebSocketGateway,
            new CameraXVisionController.Listener() {
                @Override public void onCameraReady(boolean available, boolean canSwitch) {
                    cameraAvailable = available;
                    cameraCanSwitch = canSwitch;
                    updateVisionControls();
                }

                @Override public void onEnabledChanged(boolean enabled) {
                    if (!enabled) setDocumentUi(false, false);
                    updateVisionControls();
                }

                @Override public void onError(String message) {
                    showStatus(message, false);
                }

                @Override public void onDocumentStateChanged(
                    boolean documentMode, boolean busy
                ) {
                    setDocumentUi(documentMode, busy);
                    updateVisionControls();
                }

                @Override public void onDocumentWaitingForServer(long documentSeq) {
                    showStatus("正在准备文件识别…", true);
                }
            }
        );
        // Session restore is asynchronous and can create the controller after onResume().
        // Carry the Activity's current lifecycle state into CameraX immediately; otherwise
        // enable() exposes a black PreviewView but never binds camera use cases.
        visionController.setForeground(foreground);
    }

    private void requestVisionTicketAndEnable() {
        if (destroyed || role == Role.ANONYMOUS || visionSessionGateway == null
            || visionWebSocketGateway == null || visionController == null
            || visionClientSessionId.isEmpty() || visionTicketRequestInFlight
            || authGateway == null) return;
        visionTicketRequestInFlight = true;
        updateVisionControls();
        showStatus("正在建立本轮视觉连接…", true);
        String clientSessionId = visionClientSessionId;
        // A digital-human Activity can remain alive longer than the access token. Refresh it
        // through the native broker before requesting a paid visual channel instead of turning
        // an expired access token into a hidden visual button on the next entry.
        try {
            authGateway.restore(new GatewayCallback<UserProfile>() {
                @Override public void onSuccess(UserProfile profile) {
                    runOnUiThread(() -> createVisionSessionAfterRestore(clientSessionId, profile));
                }

                @Override public void onError(ApiFailure error) {
                    runOnUiThread(() -> onVisionAuthUnavailable());
                }
            });
        } catch (RuntimeException unavailable) {
            onVisionAuthUnavailable();
        }
    }

    private void onVisionAuthUnavailable() {
        visionTicketRequestInFlight = false;
        updateVisionControls();
        showStatus("无法验证视觉登录状态，语音对话仍可继续", false);
    }

    private void createVisionSessionAfterRestore(String clientSessionId, UserProfile profile) {
        if (destroyed || sessionTerminated) return;
        if (profile == null || profile.getRole() == Role.ANONYMOUS) {
            role = Role.ANONYMOUS;
            visionTicketRequestInFlight = false;
            visionToggle.setVisibility(View.GONE);
            cameraSwitch.setVisibility(View.GONE);
            showStatus("登录状态已失效，请返回工作台重新登录", false);
            return;
        }
        role = profile.getRole();
        visionSessionGateway.create(clientSessionId, new GatewayCallback<VisionSession>() {
            @Override public void onSuccess(VisionSession value) {
                VisionSessionPolicy.Decision decision = visionSessionPolicy.validate(value);
                runOnUiThread(() -> {
                    if (destroyed || sessionTerminated) return;
                    visionTicketRequestInFlight = false;
                    if (!decision.isAllowed()) {
                        updateVisionControls();
                        showStatus("视觉会话不可用，语音对话仍可继续", false);
                        return;
                    }
                    try {
                        visionWebSocketGateway.configure(value, clientSessionId);
                        visionController.enable();
                    } catch (IllegalArgumentException invalid) {
                        showStatus("视觉会话校验失败，语音对话仍可继续", false);
                    }
                    updateVisionControls();
                });
            }

            @Override public void onError(ApiFailure error) {
                runOnUiThread(() -> {
                    visionTicketRequestInFlight = false;
                    updateVisionControls();
                    showStatus("无法建立视觉连接，语音对话仍可继续", false);
                });
            }
        });
    }

    private void toggleVision() {
        if (visionController == null || visionClientSessionId.isEmpty() || !cameraAvailable) return;
        if (visionController.isEnabled()) {
            visionController.disable();
            showStatus("视觉辅助已关闭", false);
            return;
        }
        boolean accepted = getSharedPreferences(VISION_PREFS, MODE_PRIVATE)
            .getBoolean(VISION_NOTICE_ACCEPTED, false);
        if (accepted) {
            beginVisionEnable();
            return;
        }
        new AlertDialog.Builder(this)
            .setTitle(R.string.digital_human_vision_notice_title)
            .setMessage(R.string.digital_human_vision_notice_message)
            .setNegativeButton(R.string.digital_human_vision_notice_cancel, null)
            .setPositiveButton(R.string.digital_human_vision_notice_continue, (dialog, which) -> {
                getSharedPreferences(VISION_PREFS, MODE_PRIVATE)
                    .edit().putBoolean(VISION_NOTICE_ACCEPTED, true).apply();
                beginVisionEnable();
            })
            .show();
    }

    private void beginVisionEnable() {
        if (destroyed || visionController == null || visionClientSessionId.isEmpty()
            || !cameraAvailable || visionTicketRequestInFlight) return;
        if (pendingAudioPermission != null) {
            cameraEnableQueued = true;
            showStatus("请先完成麦克风授权，再开启视觉辅助", false);
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            == PackageManager.PERMISSION_GRANTED) {
            requestVisionTicketAndEnable();
            return;
        }
        cameraPermissionInFlight = true;
        updateVisionControls();
        cameraPermissionLauncher.launch(Manifest.permission.CAMERA);
    }

    private void onCameraPermissionResult(boolean granted) {
        cameraPermissionInFlight = false;
        PermissionRequest audio = pendingAudioPermission;
        if (audio != null) {
            cameraEnableQueued = granted;
            if (!granted && !destroyed) {
                showStatus("未授予摄像头权限，语音对话仍可继续", false);
            }
            requestAudioPermission(audio);
            if (pendingAudioPermission == null && cameraEnableQueued) {
                cameraEnableQueued = false;
                beginVisionEnable();
            }
            updateVisionControls();
            return;
        }
        if (granted && !destroyed && visionController != null) {
            requestVisionTicketAndEnable();
        } else if (!granted && !destroyed) {
            showStatus("未授予摄像头权限，语音对话仍可继续", false);
        }
        updateVisionControls();
    }

    private void enterDocumentMode() {
        if (destroyed || visionController == null || !visionController.isEnabled()) return;
        if (documentInteractionBusy) {
            showStatus("请等待当前语音或回答结束后再识别文件", false);
            return;
        }
        if (visionController.enterDocumentMode()) {
            setDocumentUi(true, false);
            showStatus("请把文件放平、居中并避免反光，然后点击拍照识别", false);
        }
    }

    private void captureDocument() {
        if (destroyed || visionController == null || !visionController.isDocumentMode()) return;
        if (visionController.captureDocument()) {
            setDocumentUi(true, true);
            showStatus("正在拍摄文件…", true);
        }
    }

    private void cancelDocumentMode() {
        if (destroyed || visionController == null) return;
        if (visionController.cancelDocumentMode()) {
            setDocumentUi(false, false);
            showStatus("已取消文件识别", false);
        }
    }

    private void setDocumentUi(boolean documentMode, boolean busy) {
        if (documentOverlay == null || visionPreviewContainer == null
            || documentCapture == null || documentCancel == null) return;
        documentOverlay.setVisibility(documentMode ? View.VISIBLE : View.GONE);
        documentCapture.setEnabled(documentMode && !busy);
        documentCapture.setText(R.string.digital_human_document_capture);
        documentCancel.setEnabled(documentMode && !busy);
        if (documentMode) {
            FrameLayout.LayoutParams fullscreen = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            );
            visionPreviewContainer.setLayoutParams(fullscreen);
            visionPreviewContainer.bringToFront();
            documentOverlay.bringToFront();
            findViewById(R.id.digitalHumanStatusPanel).bringToFront();
        } else if (compactPreviewLayoutParams != null) {
            visionPreviewContainer.setLayoutParams(compactPreviewLayoutParams);
        }
    }

    private void updateVisionControls() {
        if (visionToggle == null || cameraSwitch == null || documentRecognize == null
            || role == Role.ANONYMOUS) return;
        boolean enabled = visionController != null && visionController.isEnabled();
        boolean documentMode = visionController != null && visionController.isDocumentMode();
        boolean documentBusy = visionController != null
            && visionController.isDocumentCaptureBusy();
        if (visionPreviewContainer != null) {
            visionPreviewContainer.setVisibility(enabled ? View.VISIBLE : View.GONE);
        }
        visionToggle.setVisibility(View.VISIBLE);
        visionToggle.setEnabled(!visionClientSessionId.isEmpty() && cameraAvailable
            && !cameraPermissionInFlight && !visionTicketRequestInFlight
            && !documentMode && !documentBusy);
        visionToggle.setText(enabled
            ? R.string.digital_human_vision_disable : R.string.digital_human_vision_enable);
        cameraSwitch.setVisibility(
            enabled && cameraCanSwitch && !documentMode ? View.VISIBLE : View.GONE
        );
        documentRecognize.setVisibility(enabled && !documentMode ? View.VISIBLE : View.GONE);
        documentRecognize.setEnabled(enabled && !documentBusy && !documentInteractionBusy);
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
                    if (role != Role.ANONYMOUS) {
                        visionClientSessionId = value.getSessionId();
                        updateVisionControls();
                    }
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
            case "checking_browser":
                documentInteractionBusy = true;
                showStatus("正在检查 System WebView 兼容性…", true);
                break;
            case "creating":
                documentInteractionBusy = true;
                showStatus("正在创建数字人交互任务…", true);
                break;
            case "ready":
                documentInteractionBusy = false;
                showStatus("数字人已就绪，请点击页面中的开始对话", false);
                break;
            case "active":
                documentInteractionBusy = false;
                showStatus("数字人正在聆听", false);
                break;
            case "asr_partial":
                documentInteractionBusy = true;
                if (visionController != null) visionController.onSpeechPartial();
                showStatus("正在实时识别您的问题…", true);
                break;
            case "asr_final":
                documentInteractionBusy = true;
                if (visionController != null) visionController.onSpeechFinal();
                showStatus("语音识别完成，正在生成回答…", true);
                break;
            case "answering":
                documentInteractionBusy = true;
                showStatus("数字人正在回答", false);
                break;
            case "ended":
                documentInteractionBusy = true;
                showStatus("本次数字人会话已结束", false);
                break;
            case "unsupported":
                documentInteractionBusy = true;
                showFatal("当前 Android System WebView 未通过 MetaStudio checkBrowserSupport");
                break;
            case "sdk_missing":
                documentInteractionBusy = true;
                showFatal("MetaStudio Web SDK 未正确加载");
                break;
            case "error":
                documentInteractionBusy = true;
                showStatus("数字人交互暂时不可用", false);
                break;
            default: showStatus("数字人状态已更新", false);
        }
        updateVisionControls();
    }

    private DigitalHumanWebViewClient.Listener pageListener() {
        return new DigitalHumanWebViewClient.Listener() {
            @Override public void onPageReady() { showStatus("数字人安全页面已加载", true); }
            @Override public void onBlocked(String code, String message) { showStatus(message, false); }
            @Override public void onRendererGone(WebView deadView, String message) {
                showStatus(message, false);
                sessionTerminated = true;
                foreground = false;
                destroyVision();
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
                    if (pendingAudioPermission == request) {
                        pendingAudioPermission = null;
                        boolean enableCamera = cameraEnableQueued;
                        cameraEnableQueued = false;
                        if (enableCamera) beginVisionEnable();
                    }
                });
            }
        };
    }

    private void requestAudioPermission(PermissionRequest request) {
        if (destroyed || request == null) return;
        if (cameraPermissionInFlight) {
            if (pendingAudioPermission != null && pendingAudioPermission != request) {
                pendingAudioPermission.deny();
            }
            pendingAudioPermission = request;
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED) {
            if (pendingAudioPermission == request) pendingAudioPermission = null;
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
        if (request != null) {
            if (grantResults.length == 1 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
            } else {
                request.deny();
                showStatus("未授予麦克风权限，无法使用 SIS 语音交互", false);
            }
        }
        boolean enableCamera = cameraEnableQueued;
        cameraEnableQueued = false;
        if (enableCamera) beginVisionEnable();
    }

    private void showStatus(String message, boolean busy) {
        if (destroyed || status == null || progress == null) return;
        status.setText(message == null || message.trim().isEmpty() ? "数字人状态已更新" : message);
        progress.setVisibility(busy ? View.VISIBLE : View.GONE);
    }

    private void showFatal(String message) {
        showStatus(message, false);
        if (visionController != null && visionController.isEnabled()) visionController.disable();
        if (webView != null) webView.setVisibility(View.INVISIBLE);
    }

    @Override
    protected void onResume() {
        super.onResume();
        foreground = true;
        if (visionController != null) visionController.setForeground(true);
        if (webView != null) webView.onResume();
    }

    @Override
    protected void onPause() {
        foreground = false;
        if (visionController != null) visionController.setForeground(false);
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
        if (!isFinishing() && !isChangingConfigurations()) finish();
    }

    private void terminateSession() {
        if (sessionTerminated) return;
        sessionTerminated = true;
        PermissionRequest request = pendingAudioPermission;
        pendingAudioPermission = null;
        if (request != null) request.deny();
        destroyVision();
        if (api != null) api.cancelAll();
        DigitalHumanWebViewHost.destroy(webView);
        webView = null;
    }

    private void destroyVision() {
        CameraXVisionController controller = visionController;
        visionController = null;
        if (controller != null) {
            controller.destroy();
        } else if (visionWebSocketGateway != null) {
            visionWebSocketGateway.destroy();
        }
        visionWebSocketGateway = null;
        visionSessionGateway = null;
        visionClientSessionId = "";
        visionTicketRequestInFlight = false;
        cameraAvailable = false;
        cameraCanSwitch = false;
        cameraEnableQueued = false;
        if (visionPreview != null) visionPreview.setVisibility(View.GONE);
        if (visionToggle != null) visionToggle.setEnabled(false);
        if (cameraSwitch != null) cameraSwitch.setVisibility(View.GONE);
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        terminateSession();
        super.onDestroy();
    }
}
