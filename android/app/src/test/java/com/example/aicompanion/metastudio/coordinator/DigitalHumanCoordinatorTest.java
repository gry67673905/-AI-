package com.example.aicompanion.metastudio.coordinator;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import com.example.aicompanion.metastudio.business.DigitalHumanSessionPolicy;
import com.example.aicompanion.metastudio.gateway.DigitalHumanGateway;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.NavigationIntent;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.SemanticIntent;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.JsonElement;

import org.junit.Test;

import java.util.concurrent.atomic.AtomicInteger;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicReference;

public class DigitalHumanCoordinatorTest {
    @Test
    public void anonymousIntentRoutesToLoginWithoutPrivateExchange() {
        FakeGateway gateway = new FakeGateway();
        DigitalHumanCoordinator coordinator = new DigitalHumanCoordinator(gateway, Role.ANONYMOUS);
        coordinator.createSession(new GatewayCallback<ClientSession>() {
            @Override public void onSuccess(ClientSession value) {}
            @Override public void onError(ApiFailure error) { throw new AssertionError(error.getMessage()); }
        });
        AtomicReference<NavigationIntent> result = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        coordinator.exchange(new SemanticIntent("chat-1", "intent-1"), exchange(result, failure));

        assertNull(failure.get());
        assertEquals("login", result.get().getSection());
        assertEquals("OPEN_LOGIN", result.get().getType());
        assertEquals(0, gateway.exchangeCalls.get());
    }

    @Test
    public void duplicateFinalPacketIsNotExchangedTwice() {
        FakeGateway gateway = new FakeGateway();
        DigitalHumanCoordinator coordinator = new DigitalHumanCoordinator(gateway, Role.CITIZEN);
        coordinator.createSession(new GatewayCallback<ClientSession>() {
            @Override public void onSuccess(ClientSession value) {}
            @Override public void onError(ApiFailure error) { throw new AssertionError(error.getMessage()); }
        });
        SemanticIntent semantic = new SemanticIntent("chat-1", "intent-1");
        coordinator.exchange(semantic, exchange(new AtomicReference<>(), new AtomicReference<>()));
        coordinator.exchange(semantic, exchange(new AtomicReference<>(), new AtomicReference<>()));

        assertEquals(1, gateway.exchangeCalls.get());
    }

    private static DigitalHumanCoordinator.ExchangeCallback exchange(
        AtomicReference<NavigationIntent> value,
        AtomicReference<ApiFailure> failure
    ) {
        return new DigitalHumanCoordinator.ExchangeCallback() {
            @Override public void onSuccess(NavigationIntent intent) { value.set(intent); }
            @Override public void onDuplicate() {}
            @Override public void onError(ApiFailure error) { failure.set(error); }
        };
    }

    private static final class FakeGateway implements DigitalHumanGateway {
        private final AtomicInteger exchangeCalls = new AtomicInteger();

        @Override public void createClientSession(GatewayCallback<ClientSession> callback) {
            callback.onSuccess(new ClientSession(
                "session-1", "once-code-value", "robot-1",
                DigitalHumanSessionPolicy.BEIJING_FOUR_SERVER,
                Instant.now().plusSeconds(120).toString()
            ));
        }

        @Override public void exchangeActionIntent(
            String intentId,
            String sessionId,
            String chatId,
            GatewayCallback<JsonElement> callback
        ) {
            exchangeCalls.incrementAndGet();
            callback.onSuccess(com.google.gson.JsonParser.parseString(
                "{\"intent_id\":\"intent-1\",\"type\":\"OPEN_APPLICATION\","
                    + "\"label\":\"查看办件\",\"section\":\"applications\","
                    + "\"prefill\":{},\"requires_confirmation\":true}"
            ));
        }
    }
}
