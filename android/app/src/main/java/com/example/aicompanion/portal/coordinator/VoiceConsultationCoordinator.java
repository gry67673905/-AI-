package com.example.aicompanion.portal.coordinator;

import com.example.aicompanion.portal.gateway.StreamingGateway;
import com.google.gson.JsonObject;

/** Both typed and voice consultations use the same bounded server-side streaming endpoint. */
public final class VoiceConsultationCoordinator {
    private final StreamingGateway gateway;

    public VoiceConsultationCoordinator(StreamingGateway gateway) { this.gateway = gateway; }
    public void stream(JsonObject payload, StreamingGateway.StreamCallback callback) {
        gateway.streamChat(payload, callback);
    }
}
