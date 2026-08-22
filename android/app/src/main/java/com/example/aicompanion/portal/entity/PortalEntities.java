package com.example.aicompanion.portal.entity;

import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.JsonObject;
import com.google.gson.annotations.SerializedName;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Strongly typed read models used at native boundaries; no Android or transport dependencies. */
public final class PortalEntities {
    private PortalEntities() {}

    public static final class Account {
        private String id;
        private String username;
        @SerializedName("display_name") private String displayName;
        private Role role;
        @SerializedName("applicant_type") private ApplicantType applicantType;
        private boolean active;

        public String getId() { return safe(id); }
        public String getUsername() { return safe(username); }
        public String getDisplayName() { return safe(displayName); }
        public Role getRole() { return role == null ? Role.ANONYMOUS : role; }
        public ApplicantType getApplicantType() { return applicantType == null ? ApplicantType.NONE : applicantType; }
        public boolean isActive() { return active; }
    }

    public static final class GovernmentService {
        private String id;
        private String code;
        private String title;
        private String summary;
        @SerializedName("applicant_type") private ApplicantType applicantType;
        private String status;
        @SerializedName("fee_required") private boolean feeRequired;
        @SerializedName("appointment_supported") private boolean appointmentSupported;
        @SerializedName("requires_verification") private boolean requiresVerification;
        @SerializedName("delivery_supported") private boolean deliverySupported;
        @SerializedName("delivery_options") private List<String> deliveryOptions;
        @SerializedName("mail_supported") private boolean mailSupported;

        public String getId() { return safe(id); }
        public String getCode() { return safe(code); }
        public String getTitle() { return safe(title); }
        public String getSummary() { return safe(summary); }
        public ApplicantType getApplicantType() { return applicantType == null ? ApplicantType.NONE : applicantType; }
        public String getStatus() { return safe(status); }
        public boolean isFeeRequired() { return feeRequired; }
        public boolean isAppointmentSupported() { return appointmentSupported; }
        public boolean isVerificationRequired() { return requiresVerification; }
        public boolean isDeliverySupported() { return deliverySupported; }
        public List<String> getDeliveryOptions() {
            return deliveryOptions == null
                ? Collections.emptyList()
                : Collections.unmodifiableList(new ArrayList<>(deliveryOptions));
        }
        public boolean isMailSupported() { return mailSupported; }
    }

    public static final class DynamicForm {
        @SerializedName("service_id") private String serviceId;
        private JsonObject schema;
        public String getServiceId() { return safe(serviceId); }
        public JsonObject getSchema() { return schema == null ? new JsonObject() : schema.deepCopy(); }
    }

    public static final class MaterialRequirement {
        private String id;
        private String code;
        private String name;
        private String kind;
        @SerializedName("trigger_reason") private String triggerReason;
        public String getId() { return safe(id); }
        public String getCode() { return safe(code); }
        public String getName() { return safe(name); }
        public String getKind() { return safe(kind); }
        public String getTriggerReason() { return safe(triggerReason); }
    }

    public static final class Application {
        private String id;
        @SerializedName("service_id") private String serviceId;
        private String status;
        @SerializedName("form_data") private JsonObject formData;
        private int version;
        @SerializedName("created_at") private String createdAt;
        @SerializedName("updated_at") private String updatedAt;
        public String getId() { return safe(id); }
        public String getServiceId() { return safe(serviceId); }
        public String getStatus() { return safe(status); }
        public JsonObject getFormData() { return formData == null ? new JsonObject() : formData.deepCopy(); }
        public int getVersion() { return version; }
        public String getCreatedAt() { return safe(createdAt); }
        public String getUpdatedAt() { return safe(updatedAt); }
    }

    public static final class ApplicationMaterial {
        private String id;
        @SerializedName("requirement_code") private String requirementCode;
        @SerializedName("file_name") private String fileName;
        @SerializedName("mime_type") private String mimeType;
        private long size;
        @SerializedName("scan_status") private String scanStatus;
        public String getId() { return safe(id); }
        public String getRequirementCode() { return safe(requirementCode); }
        public String getFileName() { return safe(fileName); }
        public String getMimeType() { return safe(mimeType); }
        public long getSize() { return size; }
        public String getScanStatus() { return safe(scanStatus); }
    }

    public static final class ReviewTask {
        private String id;
        @SerializedName("application_id") private String applicationId;
        private String status;
        @SerializedName("assigned_staff_id") private String assignedStaffId;
        public String getId() { return safe(id); }
        public String getApplicationId() { return safe(applicationId); }
        public String getStatus() { return safe(status); }
        public String getAssignedStaffId() { return safe(assignedStaffId); }
    }

    public static final class Appointment {
        private String id;
        @SerializedName("service_id") private String serviceId;
        @SerializedName("window_id") private String windowId;
        @SerializedName("slot_start") private String slotStart;
        private String status;
        public String getId() { return safe(id); }
        public String getServiceId() { return safe(serviceId); }
        public String getWindowId() { return safe(windowId); }
        public String getSlotStart() { return safe(slotStart); }
        public String getStatus() { return safe(status); }
    }

    public static final class PaymentOrder {
        private String id;
        @SerializedName("application_id") private String applicationId;
        private String status;
        @SerializedName("amount_cents") private long amountCents;
        public String getId() { return safe(id); }
        public String getApplicationId() { return safe(applicationId); }
        public String getStatus() { return safe(status); }
        public long getAmountCents() { return amountCents; }
    }

    public static final class Consultation {
        private String id;
        @SerializedName("session_id") private String sessionId;
        private String status;
        private String subject;
        public String getId() { return safe(id); }
        public String getSessionId() { return safe(sessionId); }
        public String getStatus() { return safe(status); }
        public String getSubject() { return safe(subject); }
    }

    public static final class AuditEvent {
        private String id;
        private String action;
        @SerializedName("actor_id") private String actorId;
        @SerializedName("created_at") private String createdAt;
        private JsonObject detail;
        public String getId() { return safe(id); }
        public String getAction() { return safe(action); }
        public String getActorId() { return safe(actorId); }
        public String getCreatedAt() { return safe(createdAt); }
        public JsonObject getDetail() { return detail == null ? new JsonObject() : detail.deepCopy(); }
    }

    public static final class ListResult<T> {
        private List<T> items;
        private int total;
        public List<T> getItems() {
            return items == null ? Collections.emptyList() : Collections.unmodifiableList(new ArrayList<>(items));
        }
        public int getTotal() { return total; }
    }

    private static String safe(String value) { return value == null ? "" : value; }
}
