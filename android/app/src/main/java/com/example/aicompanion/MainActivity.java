package com.example.aicompanion;

import android.content.pm.PackageManager;
import android.content.Intent;
import android.os.Bundle;
import android.webkit.WebView;
import android.widget.Button;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.lifecycle.ViewModelProvider;

import com.example.aicompanion.core.HmsCoreHelper;
import com.example.aicompanion.metastudio.boundary.DigitalHumanWebViewHost;
import com.example.aicompanion.metastudio.business.DigitalHumanActionPolicy;
import com.example.aicompanion.metastudio.business.DigitalHumanAvailability;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.NavigationIntent;
import com.example.aicompanion.portal.PortalGraph;
import com.example.aicompanion.portal.boundary.DocumentPickerBoundary;
import com.example.aicompanion.portal.boundary.MaterialDocumentSaveBoundary;
import com.example.aicompanion.portal.boundary.PortalJsBoundary;
import com.example.aicompanion.portal.boundary.SecureWebViewHost;
import com.example.aicompanion.portal.boundary.ServiceNavigationBoundary;
import com.example.aicompanion.portal.boundary.TextToSpeechBoundary;
import com.example.aicompanion.portal.boundary.VoiceCaptureBoundary;
import com.example.aicompanion.portal.business.RoleNavigationPolicy;
import com.example.aicompanion.portal.coordinator.PortalCoordinatorViewModel;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.example.aicompanion.portal.model.PortalContract.UiState;
import com.example.aicompanion.web.SecureAssetWebViewClient;
import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

/** Thin lifecycle host. Business decisions and HTTP calls live outside the Activity. */
public final class MainActivity extends AppCompatActivity implements PortalJsBoundary.Host {
    private final Gson gson = new Gson();
    private final RoleNavigationPolicy navigationPolicy = new RoleNavigationPolicy();
    private final DigitalHumanActionPolicy digitalHumanActionPolicy = new DigitalHumanActionPolicy();
    private final ActivityResultLauncher<Intent> digitalHumanLauncher = registerForActivityResult(
        new ActivityResultContracts.StartActivityForResult(),
        result -> onDigitalHumanResult(result.getResultCode(), result.getData())
    );

    private WebView portalWebView;
    private PortalCoordinatorViewModel viewModel;
    private DocumentPickerBoundary documentPicker;
    private MaterialDocumentSaveBoundary materialDocumentSave;
    private VoiceCaptureBoundary voiceCapture;
    private TextToSpeechBoundary speechOutput;
    private ServiceNavigationBoundary serviceNavigation;
    private UiState lastState;
    private boolean pageReady;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        PortalGraph graph = PortalGraph.create(getApplicationContext());
        viewModel = new ViewModelProvider(this, graph.viewModelFactory()).get(PortalCoordinatorViewModel.class);
        documentPicker = new DocumentPickerBoundary(this, documentListener());
        materialDocumentSave = new MaterialDocumentSaveBoundary(
            this, graph.materialDocumentGateway(), savedInstanceState, materialDocumentListener()
        );
        voiceCapture = new VoiceCaptureBoundary(this, voiceListener());
        speechOutput = new TextToSpeechBoundary(this);
        serviceNavigation = new ServiceNavigationBoundary(this, this::dispatchBoundaryError);

        portalWebView = findViewById(R.id.assistantWebView);
        configureDigitalHumanLaunch(findViewById(R.id.openDigitalHuman));
        SecureWebViewHost.configure(this, portalWebView, new PortalJsBoundary(this), this::onPageReady);
        viewModel.state().observe(this, this::onUiState);
        portalWebView.loadUrl(SecureAssetWebViewClient.START_URL);
    }

    private void configureDigitalHumanLaunch(Button button) {
        DigitalHumanAvailability.Decision availability = new DigitalHumanAvailability().check(this);
        boolean enabled = availability.isAvailable() && DigitalHumanWebViewHost.isMessagingSupported();
        // Keep the control actionable so unsupported devices receive a visible
        // explanation instead of a silently disabled button.
        button.setEnabled(true);
        button.setText(enabled ? R.string.digital_human_open : R.string.digital_human_unsupported);
        button.setContentDescription(enabled
            ? "打开华为云智能交互数字人"
            : availability.getMessage());
        button.setOnClickListener(view -> {
            if (!enabled) {
                dispatchBoundaryError("digital_human_unavailable", availability.getMessage());
                return;
            }
            if (!viewModel.isSessionRestoreComplete()) {
                dispatchBoundaryError("session_restoring", "正在恢复安全登录状态，请稍后再试");
                return;
            }
            // MetaStudio/SIS exclusively owns the microphone and remote speech
            // while its isolated Activity is active. Tear down any ordinary
            // portal recognizer and stop local TTS before opening it; install a
            // fresh, idle boundary so normal chat remains available on return.
            if (voiceCapture != null) voiceCapture.destroy();
            voiceCapture = new VoiceCaptureBoundary(this, voiceListener());
            if (speechOutput != null) speechOutput.stop();
            digitalHumanLauncher.launch(new Intent(this, DigitalHumanActivity.class));
        });
    }

    private void onDigitalHumanResult(int resultCode, Intent data) {
        if (resultCode != RESULT_OK || data == null) return;
        String raw = data.getStringExtra(DigitalHumanActivity.EXTRA_NAVIGATION_JSON);
        if (raw == null || raw.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 16 * 1024) {
            dispatchBoundaryError("invalid_digital_human_result", "数字人操作建议无效");
            return;
        }
        try {
            DigitalHumanActionPolicy.Decision decision = digitalHumanActionPolicy.validatePortalEvent(
                JsonParser.parseString(raw), viewModel.currentRole()
            );
            if (!decision.isAllowed()) {
                dispatchBoundaryError(decision.getCode(), decision.getMessage());
                return;
            }
            NavigationIntent intent = decision.getIntent();
            dispatch("onNativeAux", intent.toPortalEvent());
        } catch (RuntimeException invalid) {
            dispatchBoundaryError("invalid_digital_human_result", "数字人操作建议格式无效");
        }
    }

    @Override
    public void executeCommand(String envelopeJson) {
        runOnUiThread(() -> viewModel.executeBridgeCommand(envelopeJson));
    }

    @Override
    public void chooseDocument(String requestJson) {
        runOnUiThread(() -> documentPicker.choose(requestJson, viewModel.currentRole()));
    }

    @Override
    public void controlVoice(String action) {
        runOnUiThread(() -> {
            if ("start".equals(action)) voiceCapture.start();
            else if ("stop".equals(action)) voiceCapture.stop();
            else dispatchBoundaryError("invalid_voice_action", "仅支持 start 或 stop 语音命令");
        });
    }

    @Override
    public void openServiceNavigation(String serviceId) {
        runOnUiThread(() -> serviceNavigation.open(serviceId));
    }

    @Override
    public void saveGeneratedDocument(String generationId) {
        runOnUiThread(() -> materialDocumentSave.save(generationId, viewModel.currentRole()));
    }

    private void onPageReady() {
        pageReady = true;
        JsonObject ready = new JsonObject();
        ready.addProperty("demo", true);
        ready.addProperty("hms_status", HmsCoreHelper.describe(this));
        ready.add("user", gson.toJsonTree(viewModel.currentUser()));
        ready.add("sections", gson.toJsonTree(navigationPolicy.sections(viewModel.currentRole())));
        ready.addProperty("max_material_bytes", 10L * 1024L * 1024L);
        ready.addProperty("chat_session_id", viewModel.currentChatSessionId());
        ready.addProperty("material_generation_id", viewModel.currentMaterialGenerationId());
        dispatch("onNativeReady", ready);
        if (lastState != null) dispatchState(lastState);
    }

    private void onUiState(UiState state) {
        lastState = state;
        if (pageReady) dispatchState(state);
        if (state.shouldSpeakAnswer() && viewModel.consumeSpeech(state.getSequence())) {
            String answer = state.getData() != null && state.getData().isJsonObject()
                && state.getData().getAsJsonObject().has("answer")
                ? state.getData().getAsJsonObject().get("answer").getAsString() : "";
            speechOutput.speak(answer);
        }
    }

    private void dispatchState(UiState state) {
        dispatch("onNativeState", gson.toJsonTree(state));
    }

    private DocumentPickerBoundary.Listener documentListener() {
        return new DocumentPickerBoundary.Listener() {
            @Override public void onSelected(SelectedDocument document) { viewModel.uploadDocument(document); }
            @Override public void onCancelled() {
                JsonObject event = new JsonObject();
                event.addProperty("type", "document_cancelled");
                dispatch("onNativeAux", event);
            }
            @Override public void onError(String code, String message) { dispatchBoundaryError(code, message); }
        };
    }

    private VoiceCaptureBoundary.Listener voiceListener() {
        return new VoiceCaptureBoundary.Listener() {
            @Override public void onState(String state) {
                JsonObject event = new JsonObject();
                event.addProperty("type", "voice_state");
                event.addProperty("state", state);
                dispatch("onNativeAux", event);
            }
            @Override public void onPartial(String text) {
                JsonObject event = new JsonObject();
                event.addProperty("type", "voice_partial");
                event.addProperty("text", text);
                dispatch("onNativeAux", event);
            }
            @Override public void onFinal(String text) {
                JsonObject event = new JsonObject();
                event.addProperty("type", "voice_final");
                event.addProperty("text", text);
                dispatch("onNativeAux", event);
                viewModel.executeVoiceMessage(text);
            }
            @Override public void onError(String code, String message) { dispatchBoundaryError(code, message); }
        };
    }

    private MaterialDocumentSaveBoundary.Listener materialDocumentListener() {
        return new MaterialDocumentSaveBoundary.Listener() {
            @Override public void onPreparing() {
                JsonObject event = new JsonObject();
                event.addProperty("type", "material_document_preparing");
                dispatch("onNativeAux", event);
            }

            @Override public void onSaved(String displayName, boolean opened) {
                JsonObject event = new JsonObject();
                event.addProperty("type", "material_document_saved");
                event.addProperty("display_name", displayName);
                event.addProperty("opened", opened);
                dispatch("onNativeAux", event);
            }

            @Override public void onCancelled() {
                JsonObject event = new JsonObject();
                event.addProperty("type", "material_document_save_cancelled");
                dispatch("onNativeAux", event);
            }

            @Override public void onAuthenticationRequired(ApiFailure error) {
                viewModel.handleBoundaryApiFailure("MATERIAL_DOCUMENT_DOWNLOAD", error);
            }

            @Override public void onError(String code, String message) {
                dispatchBoundaryError(code, message);
            }
        };
    }

    private void dispatchBoundaryError(String code, String message) {
        runOnUiThread(() -> {
            JsonObject event = new JsonObject();
            event.addProperty("type", "boundary_error");
            event.addProperty("code", code);
            event.addProperty("message", message);
            dispatch("onNativeAux", event);
        });
    }

    /** Function names are native constants; only JSON data is interpolated. */
    private void dispatch(String fixedFunction, JsonElement payload) {
        if (!pageReady || portalWebView == null) return;
        final String function;
        switch (fixedFunction) {
            case "onNativeReady": function = "onNativeReady"; break;
            case "onNativeState": function = "onNativeState"; break;
            case "onNativeAux": function = "onNativeAux"; break;
            default: return;
        }
        portalWebView.evaluateJavascript(
            "window.GovPortal&&window.GovPortal." + function + "(" + gson.toJson(payload) + ");",
            null
        );
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == VoiceCaptureBoundary.RECORD_AUDIO_REQUEST) {
            voiceCapture.onPermissionResult(grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED);
        }
    }

    @Override
    protected void onSaveInstanceState(@NonNull Bundle outState) {
        if (materialDocumentSave != null) materialDocumentSave.saveState(outState);
        super.onSaveInstanceState(outState);
    }

    @Override
    protected void onDestroy() {
        pageReady = false;
        if (voiceCapture != null) voiceCapture.destroy();
        if (speechOutput != null) speechOutput.destroy();
        if (materialDocumentSave != null) materialDocumentSave.destroy(isChangingConfigurations());
        SecureWebViewHost.destroy(portalWebView);
        portalWebView = null;
        super.onDestroy();
    }
}
