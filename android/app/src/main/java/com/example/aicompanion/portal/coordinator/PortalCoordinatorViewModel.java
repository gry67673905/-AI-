package com.example.aicompanion.portal.coordinator;

import androidx.annotation.NonNull;
import androidx.lifecycle.LiveData;
import androidx.lifecycle.MutableLiveData;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import com.example.aicompanion.portal.business.PortalCommandPolicy;
import com.example.aicompanion.portal.business.SensitiveDisplayPolicy;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.StreamingGateway;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.CommandEnvelope;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.example.aicompanion.portal.model.PortalContract.UiState;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;

import java.util.EnumSet;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/** Lifecycle-retained coordinator. No callback captures an Activity or WebView. */
public final class PortalCoordinatorViewModel extends ViewModel {
    private static final EnumSet<Command> AUTH = EnumSet.of(
        Command.AUTH_SEND_CODE, Command.AUTH_REGISTER, Command.AUTH_LOGIN, Command.AUTH_LOGOUT, Command.AUTH_ME
    );
    private static final EnumSet<Command> STAFF = EnumSet.range(Command.STAFF_TASKS, Command.STAFF_HANDOFF_RESOLVE);
    private static final EnumSet<Command> ADMIN = EnumSet.range(Command.ADMIN_METRICS, Command.ADMIN_AUDIT);

    private final AuthCoordinator auth;
    private final CitizenCoordinator citizen;
    private final StaffTaskCoordinator staff;
    private final AdminCoordinator admin;
    private final VoiceConsultationCoordinator voice;
    private final PortalCommandPolicy commandPolicy;
    private final SensitiveDisplayPolicy displayPolicy;
    private final NativeApiClient api;
    private final MutableLiveData<UiState> state;
    private final AtomicLong sequence = new AtomicLong();
    private final AtomicBoolean requestInFlight = new AtomicBoolean();
    private final Object speechLock = new Object();

    private volatile UserProfile user;
    private volatile String chatSessionId = "";
    private long consumedSpeechSequence = -1;

    public PortalCoordinatorViewModel(
        AuthCoordinator auth,
        CitizenCoordinator citizen,
        StaffTaskCoordinator staff,
        AdminCoordinator admin,
        VoiceConsultationCoordinator voice,
        PortalCommandPolicy commandPolicy,
        SensitiveDisplayPolicy displayPolicy,
        NativeApiClient api
    ) {
        this.auth = auth;
        this.citizen = citizen;
        this.staff = staff;
        this.admin = admin;
        this.voice = voice;
        this.commandPolicy = commandPolicy;
        this.displayPolicy = displayPolicy;
        this.api = api;
        this.user = auth.restoredProfile();
        this.state = new MutableLiveData<>(UiState.idle(user));
        restoreSession();
    }

    public LiveData<UiState> state() { return state; }
    public Role currentRole() { return user.getRole(); }
    public UserProfile currentUser() { return user; }

    public void executeBridgeCommand(String rawEnvelope) {
        PortalCommandPolicy.Decision decision = commandPolicy.validate(rawEnvelope, currentRole());
        if (!decision.isAllowed()) {
            emitError("", "", new ApiFailure(400, decision.getCode(), decision.getMessage()));
            return;
        }
        CommandEnvelope envelope = decision.getEnvelope();
        execute(envelope.getCommand(), envelope.getRequestId(), envelope.getPayload(), false);
    }

    public void executeVoiceMessage(String rawText) {
        String message = rawText == null ? "" : rawText.trim();
        int length = message.codePointCount(0, message.length());
        if (length == 0 || length > 1000) {
            emitError("CHAT_STREAM", "", new ApiFailure(400, "validation_error", "语音识别文本长度无效"));
            return;
        }
        JsonObject payload = new JsonObject();
        payload.addProperty("message", message);
        execute(Command.CHAT_STREAM, "voice-" + UUID.randomUUID(), payload, true);
    }

    public void uploadDocument(SelectedDocument document) {
        if (document == null) {
            emitError("DOCUMENT_UPLOAD", "", new ApiFailure(400, "invalid_document", "未选择文件"));
            return;
        }
        if (!requestInFlight.compareAndSet(false, true)) {
            emit("error", "DOCUMENT_UPLOAD", "", true, new JsonObject(),
                new ApiFailure(409, "request_in_progress", "另一项操作仍在处理中"), false);
            return;
        }
        final String requestId = "document-" + UUID.randomUUID();
        emit("loading", "DOCUMENT_UPLOAD", requestId, true, new JsonObject(), null, false);
        GatewayCallback<JsonElement> callback = completion("DOCUMENT_UPLOAD", requestId);
        if ("knowledge".equals(document.getPurpose()) && currentRole() == Role.ADMIN) {
            admin.uploadKnowledge(document, callback);
        } else if ("material".equals(document.getPurpose()) && currentRole() == Role.CITIZEN) {
            citizen.uploadMaterial(document, callback);
        } else {
            requestInFlight.set(false);
            emitError("DOCUMENT_UPLOAD", requestId, new ApiFailure(403, "forbidden", "当前角色不能上传此类文件"));
        }
    }

    public boolean consumeSpeech(long stateSequence) {
        synchronized (speechLock) {
            if (stateSequence <= consumedSpeechSequence) return false;
            consumedSpeechSequence = stateSequence;
            return true;
        }
    }

    private void execute(Command command, String requestId, JsonObject payload, boolean speakAnswer) {
        if (!requestInFlight.compareAndSet(false, true)) {
            emit("error", command.name(), requestId, true, new JsonObject(),
                new ApiFailure(409, "request_in_progress", "另一项操作仍在处理中"), false);
            return;
        }
        emit("loading", command.name(), requestId, true, new JsonObject(), null, false);
        if (command == Command.CHAT_STREAM) {
            startStream(requestId, payload, speakAnswer);
            return;
        }
        GatewayCallback<JsonElement> callback = completion(command.name(), requestId);
        if (AUTH.contains(command)) {
            auth.execute(command, payload, new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    if (command == Command.AUTH_LOGIN || command == Command.AUTH_REGISTER
                        || command == Command.AUTH_LOGOUT || command == Command.AUTH_ME) {
                        user = auth.restoredProfile();
                    }
                    callback.onSuccess(value);
                }
                @Override public void onError(ApiFailure error) { callback.onError(error); }
            });
        } else if (STAFF.contains(command)) {
            staff.execute(command, payload, callback);
        } else if (ADMIN.contains(command)) {
            admin.execute(command, payload, callback);
        } else {
            citizen.execute(command, payload, callback);
        }
    }

    private void startStream(String requestId, JsonObject sourcePayload, boolean speakAnswer) {
        JsonObject payload = sourcePayload.deepCopy();
        if (!chatSessionId.isEmpty() && !payload.has("session_id")) payload.addProperty("session_id", chatSessionId);
        StringBuilder accumulated = new StringBuilder();
        voice.stream(payload, new StreamingGateway.StreamCallback() {
            @Override
            public void onEvent(String type, JsonElement rawData) {
                JsonElement safe = displayPolicy.sanitize(rawData);
                rememberSession(safe);
                updateAnswer(accumulated, type, safe);
                if ("error".equals(type)) {
                    requestInFlight.set(false);
                    JsonObject object = safe != null && safe.isJsonObject() ? safe.getAsJsonObject() : new JsonObject();
                    JsonObject errorObject = object.has("error") && object.get("error").isJsonObject()
                        ? object.getAsJsonObject("error") : object;
                    JsonElement details = errorObject.get("detail");
                    if (details == null || details.isJsonNull()) details = errorObject.get("details");
                    emitError(Command.CHAT_STREAM.name(), requestId, new ApiFailure(
                        502,
                        primitive(errorObject, "code").isEmpty() ? "stream_failed" : primitive(errorObject, "code"),
                        primitive(errorObject, "message").isEmpty() ? "流式咨询暂不可用" : primitive(errorObject, "message"),
                        details
                    ));
                    return;
                }
                JsonObject stream = new JsonObject();
                stream.addProperty("event_type", type);
                stream.add("payload", safe);
                stream.addProperty("answer", accumulated.toString());
                boolean done = "done".equals(type);
                if (done) requestInFlight.set(false);
                emit(done ? "success" : "stream", Command.CHAT_STREAM.name(), requestId,
                    !done, stream, null, done && speakAnswer);
            }

            @Override
            public void onError(ApiFailure error) {
                requestInFlight.set(false);
                emitError(Command.CHAT_STREAM.name(), requestId, error);
            }
        });
    }

    private GatewayCallback<JsonElement> completion(String command, String requestId) {
        return new GatewayCallback<JsonElement>() {
            @Override public void onSuccess(JsonElement value) {
                requestInFlight.set(false);
                emit("success", command, requestId, false, displayPolicy.sanitize(value), null, false);
            }
            @Override public void onError(ApiFailure error) {
                requestInFlight.set(false);
                emitError(command, requestId, error);
            }
        };
    }

    private void restoreSession() {
        auth.restore(new GatewayCallback<UserProfile>() {
            @Override public void onSuccess(UserProfile profile) {
                user = profile;
                JsonObject payload = new JsonObject();
                payload.addProperty("restored", profile.getRole() != Role.ANONYMOUS);
                emit("session", "AUTH_RESTORE", "", false, payload, null, false);
            }
            @Override public void onError(ApiFailure error) {
                user = UserProfile.anonymous();
                emitError("AUTH_RESTORE", "", error);
            }
        });
    }

    private void rememberSession(JsonElement data) {
        if (data == null || !data.isJsonObject()) return;
        JsonObject object = data.getAsJsonObject();
        JsonElement session = object.get("session_id");
        if (session != null && session.isJsonPrimitive() && session.getAsJsonPrimitive().isString()) {
            chatSessionId = session.getAsString();
        }
        JsonElement nested = object.get("payload");
        if (nested != null && nested.isJsonObject()) rememberSession(nested);
    }

    private static void updateAnswer(StringBuilder answer, String event, JsonElement data) {
        if (data == null || data.isJsonNull()) return;
        if (data.isJsonPrimitive() && data.getAsJsonPrimitive().isString()) {
            if ("delta".equals(event) || "message".equals(event)) answer.append(data.getAsString());
            return;
        }
        if (!data.isJsonObject()) return;
        JsonObject object = data.getAsJsonObject();
        String delta = primitive(object, "delta");
        if (delta.isEmpty()) delta = primitive(object, "text");
        if (!delta.isEmpty() && !"done".equals(event)) answer.append(delta);
        String complete = primitive(object, "answer");
        if ("done".equals(event) && !complete.isEmpty()) {
            answer.setLength(0);
            answer.append(complete);
        }
    }

    private static String primitive(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString() : "";
    }

    private void emitError(String command, String requestId, ApiFailure error) {
        if (error != null && error.getStatusCode() == 401) user = auth.restoredProfile();
        emit("error", command, requestId, false, new JsonObject(), error, false);
    }

    private void emit(
        String phase,
        String command,
        String requestId,
        boolean busy,
        JsonElement data,
        ApiFailure error,
        boolean speakAnswer
    ) {
        state.postValue(new UiState(sequence.incrementAndGet(), phase, command, requestId, busy,
            user, data, error, speakAnswer));
    }

    @Override
    protected void onCleared() {
        api.cancelAll();
    }

    public static final class Factory implements ViewModelProvider.Factory {
        private final AuthCoordinator auth;
        private final CitizenCoordinator citizen;
        private final StaffTaskCoordinator staff;
        private final AdminCoordinator admin;
        private final VoiceConsultationCoordinator voice;
        private final PortalCommandPolicy commandPolicy;
        private final SensitiveDisplayPolicy displayPolicy;
        private final NativeApiClient api;

        public Factory(
            AuthCoordinator auth,
            CitizenCoordinator citizen,
            StaffTaskCoordinator staff,
            AdminCoordinator admin,
            VoiceConsultationCoordinator voice,
            PortalCommandPolicy commandPolicy,
            SensitiveDisplayPolicy displayPolicy,
            NativeApiClient api
        ) {
            this.auth = auth;
            this.citizen = citizen;
            this.staff = staff;
            this.admin = admin;
            this.voice = voice;
            this.commandPolicy = commandPolicy;
            this.displayPolicy = displayPolicy;
            this.api = api;
        }

        @NonNull
        @Override
        @SuppressWarnings("unchecked")
        public <T extends ViewModel> T create(@NonNull Class<T> modelClass) {
            if (!modelClass.isAssignableFrom(PortalCoordinatorViewModel.class)) {
                throw new IllegalArgumentException("Unknown ViewModel class: " + modelClass.getName());
            }
            return (T) new PortalCoordinatorViewModel(auth, citizen, staff, admin, voice, commandPolicy, displayPolicy, api);
        }
    }
}
