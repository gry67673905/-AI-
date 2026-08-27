package com.example.aicompanion.metastudio.coordinator;

import com.example.aicompanion.metastudio.business.DigitalHumanActionPolicy;
import com.example.aicompanion.metastudio.business.DigitalHumanSessionPolicy;
import com.example.aicompanion.metastudio.business.SemanticIntentDeduplicator;
import com.example.aicompanion.metastudio.gateway.DigitalHumanGateway;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.NavigationIntent;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.SemanticIntent;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

/** Coordinates one digital-human client session without owning an Activity or WebView. */
public final class DigitalHumanCoordinator {
    private final DigitalHumanGateway gateway;
    private final DigitalHumanSessionPolicy sessionPolicy;
    private final DigitalHumanActionPolicy actionPolicy;
    private final SemanticIntentDeduplicator deduplicator;
    private final Role role;

    private volatile ClientSession session;

    public DigitalHumanCoordinator(DigitalHumanGateway gateway, Role role) {
        this(gateway, role, new DigitalHumanSessionPolicy(), new DigitalHumanActionPolicy(),
            new SemanticIntentDeduplicator());
    }

    DigitalHumanCoordinator(
        DigitalHumanGateway gateway,
        Role role,
        DigitalHumanSessionPolicy sessionPolicy,
        DigitalHumanActionPolicy actionPolicy,
        SemanticIntentDeduplicator deduplicator
    ) {
        this.gateway = gateway;
        this.role = role == null ? Role.ANONYMOUS : role;
        this.sessionPolicy = sessionPolicy;
        this.actionPolicy = actionPolicy;
        this.deduplicator = deduplicator;
    }

    public void createSession(GatewayCallback<ClientSession> callback) {
        gateway.createClientSession(new GatewayCallback<ClientSession>() {
            @Override public void onSuccess(ClientSession value) {
                DigitalHumanSessionPolicy.Decision decision = sessionPolicy.validate(value);
                if (!decision.isAllowed()) {
                    callback.onError(new ApiFailure(502, decision.getCode(), decision.getMessage()));
                    return;
                }
                session = value;
                callback.onSuccess(value);
            }

            @Override public void onError(ApiFailure error) { callback.onError(error); }
        });
    }

    public void exchange(SemanticIntent semantic, ExchangeCallback callback) {
        ClientSession current = session;
        if (current == null) {
            callback.onError(new ApiFailure(409, "digital_human_not_ready", "数字人会话尚未就绪"));
            return;
        }
        if (semantic == null || !deduplicator.accept(semantic.getChatId(), semantic.getIntentId())) {
            callback.onDuplicate();
            return;
        }
        gateway.exchangeActionIntent(
            semantic.getIntentId(),
            current.getSessionId(),
            semantic.getChatId(),
            new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    DigitalHumanActionPolicy.Decision decision = actionPolicy.validate(
                        value, semantic.getIntentId(), role
                    );
                    if (!decision.isAllowed()) {
                        callback.onError(new ApiFailure(403, decision.getCode(), decision.getMessage()));
                        return;
                    }
                    callback.onSuccess(decision.getIntent());
                }

                @Override public void onError(ApiFailure error) { callback.onError(error); }
            }
        );
    }

    public interface ExchangeCallback {
        void onSuccess(NavigationIntent intent);
        void onDuplicate();
        void onError(ApiFailure error);
    }
}
