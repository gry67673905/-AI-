package com.example.aicompanion.portal.model;

import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.annotations.SerializedName;

import java.util.Locale;

/** Strongly typed native contracts. Authentication secrets are deliberately absent from UI types. */
public final class PortalContract {
    private PortalContract() {}

    public enum Role {
        ANONYMOUS,
        CITIZEN,
        STAFF,
        ADMIN;

        public static Role fromWire(String raw) {
            if (raw == null) return ANONYMOUS;
            try {
                return valueOf(raw.trim().toUpperCase(Locale.ROOT));
            } catch (IllegalArgumentException ignored) {
                return ANONYMOUS;
            }
        }
    }

    public enum ApplicantType {
        INDIVIDUAL,
        ENTERPRISE,
        NONE;

        public static ApplicantType fromWire(String raw) {
            if (raw == null) return NONE;
            try {
                return valueOf(raw.trim().toUpperCase(Locale.ROOT));
            } catch (IllegalArgumentException ignored) {
                return NONE;
            }
        }
    }

    public enum Command {
        AUTH_SEND_CODE,
        AUTH_REGISTER,
        AUTH_LOGIN,
        AUTH_LOGOUT,
        AUTH_ME,
        CATALOG_SEARCH,
        CATALOG_DETAILS,
        ELIGIBILITY_CHECK,
        MATERIALS_GET,
        PROCESS_GET,
        FORM_SCHEMA_GET,
        WINDOW_LIST,
        APPLICATION_CREATE,
        APPLICATION_LIST,
        APPLICATION_DETAILS,
        APPLICATION_UPDATE_FORM,
        APPLICATION_SUBMIT,
        APPLICATION_SUPPLEMENT,
        APPLICATION_WITHDRAW,
        APPLICATION_DISCARD,
        APPLICATION_TIMELINE,
        DELIVERY_SET,
        APPOINTMENT_LIST,
        APPOINTMENT_BOOK,
        APPOINTMENT_CANCEL,
        PAYMENT_CREATE,
        PAYMENT_CONFIRM,
        PAYMENT_CANCEL,
        VERIFICATION_CREATE,
        VERIFICATION_CONFIRM,
        DELIVERY_CANCEL,
        CONSULTATION_HISTORY,
        CONSULTATION_FEEDBACK,
        HANDOFF_CREATE,
        HANDOFF_MESSAGES,
        HANDOFF_MESSAGE_ADD,
        HANDOFF_CANCEL,
        CHAT_STREAM,
        STAFF_TASKS,
        STAFF_CLAIM,
        STAFF_SUPPLEMENT,
        STAFF_APPROVE,
        STAFF_REJECT,
        STAFF_COMPLETE,
        STAFF_HANDOFFS,
        STAFF_HANDOFF_REPLY,
        STAFF_HANDOFF_RESOLVE,
        ADMIN_METRICS,
        ADMIN_DEPARTMENTS,
        ADMIN_DEPARTMENT_CREATE,
        ADMIN_WINDOWS,
        ADMIN_WINDOW_CREATE,
        ADMIN_ACCOUNTS,
        ADMIN_SERVICES,
        ADMIN_STAFF_CREATE,
        ADMIN_USER_FREEZE,
        ADMIN_SERVICE_CREATE,
        ADMIN_SERVICE_VERSION,
        ADMIN_SERVICE_LIFECYCLE,
        ADMIN_KNOWLEDGE_UPLOAD,
        ADMIN_KNOWLEDGE_RETRY,
        ADMIN_KNOWLEDGE_ARCHIVE,
        ADMIN_AUDIT;

        public static Command fromWire(String raw) {
            if (raw == null) return null;
            try {
                return valueOf(raw.trim().toUpperCase(Locale.ROOT));
            } catch (IllegalArgumentException ignored) {
                return null;
            }
        }
    }

    public static final class CommandEnvelope {
        @SerializedName("request_id")
        private String requestId;
        private String command;
        private JsonObject payload;

        public String getRequestId() {
            return requestId == null ? "" : requestId;
        }

        public Command getCommand() {
            return Command.fromWire(command);
        }

        public JsonObject getPayload() {
            return payload == null ? new JsonObject() : payload.deepCopy();
        }
    }

    /** Stored only by SecureSessionStore. Never serialize this type into WebView callbacks. */
    public static final class SessionSecrets {
        @SerializedName("access_token")
        private final String accessToken;
        @SerializedName("refresh_token")
        private final String refreshToken;
        @SerializedName("token_type")
        private final String tokenType;

        public SessionSecrets(String accessToken, String refreshToken, String tokenType) {
            this.accessToken = accessToken == null ? "" : accessToken;
            this.refreshToken = refreshToken == null ? "" : refreshToken;
            this.tokenType = tokenType == null || tokenType.trim().isEmpty() ? "Bearer" : tokenType;
        }

        public String getAccessToken() { return accessToken; }
        public String getRefreshToken() { return refreshToken; }
        public String getTokenType() { return tokenType; }
        public boolean isComplete() { return !accessToken.isEmpty() && !refreshToken.isEmpty(); }
    }

    public static final class UserProfile {
        private final String id;
        private final String displayName;
        private final Role role;
        private final ApplicantType applicantType;

        public UserProfile(String id, String displayName, Role role, ApplicantType applicantType) {
            this.id = id == null ? "" : id;
            this.displayName = displayName == null ? "" : displayName;
            this.role = role == null ? Role.ANONYMOUS : role;
            this.applicantType = applicantType == null ? ApplicantType.NONE : applicantType;
        }

        public static UserProfile anonymous() {
            return new UserProfile("", "访客", Role.ANONYMOUS, ApplicantType.NONE);
        }

        public String getId() { return id; }
        public String getDisplayName() { return displayName; }
        public Role getRole() { return role; }
        public ApplicantType getApplicantType() { return applicantType; }
    }

    public static final class ApiFailure {
        @SerializedName("status_code")
        private final int statusCode;
        private final String code;
        private final String message;
        private final JsonElement details;

        public ApiFailure(int statusCode, String code, String message) {
            this(statusCode, code, message, JsonNull.INSTANCE);
        }

        public ApiFailure(int statusCode, String code, String message, JsonElement details) {
            this.statusCode = statusCode;
            this.code = code == null ? "unknown_error" : code;
            this.message = message == null ? "请求失败" : message;
            this.details = details == null ? JsonNull.INSTANCE : details.deepCopy();
        }

        public int getStatusCode() { return statusCode; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
        public JsonElement getDetails() { return details.deepCopy(); }
    }

    /** Typed chat source shared by native portal code; kind remains open for future backend values. */
    public static final class Source {
        private String kind;
        private String title;
        private String reference;
        private String excerpt;
        private Double score;

        public String getKind() { return kind == null ? "" : kind; }
        public String getTitle() { return title == null ? "" : title; }
        public String getReference() { return reference == null ? "" : reference; }
        public String getExcerpt() { return excerpt == null ? "" : excerpt; }
        public Double getScore() { return score; }
    }

    /** Typed audit-safe projection of a chat tool call. */
    public static final class ToolCall {
        private String name;
        private boolean success;
        private JsonObject arguments;
        private JsonElement result;
        @SerializedName("duration_ms")
        private int durationMs;
        private boolean cached;
        private String error;

        public String getName() { return name == null ? "" : name; }
        public boolean isSuccess() { return success; }
        public JsonObject getArguments() { return arguments == null ? new JsonObject() : arguments.deepCopy(); }
        public JsonElement getResult() { return result == null ? JsonNull.INSTANCE : result.deepCopy(); }
        public int getDurationMs() { return durationMs; }
        public boolean isCached() { return cached; }
        public String getError() { return error == null ? "" : error; }
    }

    /** Observable snapshot retained by the ViewModel across Activity recreation. */
    public static final class UiState {
        private final long sequence;
        private final String phase;
        private final String command;
        @SerializedName("request_id")
        private final String requestId;
        private final boolean busy;
        private final UserProfile user;
        private final JsonElement data;
        private final ApiFailure error;
        @SerializedName("speak_answer")
        private final boolean speakAnswer;

        public UiState(
            long sequence,
            String phase,
            String command,
            String requestId,
            boolean busy,
            UserProfile user,
            JsonElement data,
            ApiFailure error,
            boolean speakAnswer
        ) {
            this.sequence = sequence;
            this.phase = phase;
            this.command = command;
            this.requestId = requestId;
            this.busy = busy;
            this.user = user == null ? UserProfile.anonymous() : user;
            this.data = data == null ? JsonNull.INSTANCE : data;
            this.error = error;
            this.speakAnswer = speakAnswer;
        }

        public static UiState idle(UserProfile user) {
            return new UiState(0, "idle", "", "", false, user, JsonNull.INSTANCE, null, false);
        }

        public long getSequence() { return sequence; }
        public String getPhase() { return phase; }
        public String getCommand() { return command; }
        public String getRequestId() { return requestId; }
        public boolean isBusy() { return busy; }
        public UserProfile getUser() { return user; }
        public JsonElement getData() { return data; }
        public ApiFailure getError() { return error; }
        public boolean shouldSpeakAnswer() { return speakAnswer; }
    }

    public static final class SelectedDocument {
        private final String purpose;
        private final String uri;
        private final String displayName;
        private final String mimeType;
        private final long size;
        private final String applicationId;
        private final String requirementId;

        public SelectedDocument(
            String purpose,
            String uri,
            String displayName,
            String mimeType,
            long size,
            String applicationId,
            String requirementId
        ) {
            this.purpose = purpose;
            this.uri = uri;
            this.displayName = displayName;
            this.mimeType = mimeType;
            this.size = size;
            this.applicationId = applicationId;
            this.requirementId = requirementId;
        }

        public String getPurpose() { return purpose; }
        public String getUri() { return uri; }
        public String getDisplayName() { return displayName; }
        public String getMimeType() { return mimeType; }
        public long getSize() { return size; }
        public String getApplicationId() { return applicationId; }
        public String getRequirementId() { return requirementId; }
    }

    public static final class WindowLocation {
        private final String id;
        private final String name;
        private final String address;
        private final double latitude;
        private final double longitude;

        public WindowLocation(String id, String name, String address, double latitude, double longitude) {
            this.id = id;
            this.name = name;
            this.address = address;
            this.latitude = latitude;
            this.longitude = longitude;
        }

        public String getId() { return id; }
        public String getName() { return name; }
        public String getAddress() { return address; }
        public double getLatitude() { return latitude; }
        public double getLongitude() { return longitude; }
    }
}
