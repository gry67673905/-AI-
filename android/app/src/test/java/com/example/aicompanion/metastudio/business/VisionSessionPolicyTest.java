package com.example.aicompanion.metastudio.business;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.metastudio.model.DigitalHumanContract.VisionSession;

import org.junit.Test;

import java.lang.reflect.Method;

public final class VisionSessionPolicyTest {
    @Test
    public void acceptsFreshNativeTicketAndRejectsExpiredOrHeaderInjection() {
        VisionSessionPolicy policy = new VisionSessionPolicy();
        assertTrue(policy.validate(new VisionSession(
            "vision-1", "wss://api.example.test/api/v1/integrations/metastudio/vision/ws",
            "vision-token-123456", "2099-01-01T00:00:00Z"
        )).isAllowed());
        assertFalse(policy.validate(new VisionSession(
            "vision-1", "wss://api.example.test/api/v1/integrations/metastudio/vision/ws",
            "vision-token-123456", "2020-01-01T00:00:00Z"
        )).isAllowed());
        assertFalse(policy.validate(new VisionSession(
            "vision-1", "wss://api.example.test/api/v1/integrations/metastudio/vision/ws",
            "vision-token\r\ninjected", "2099-01-01T00:00:00Z"
        )).isAllowed());
        assertFalse(policy.validate(new VisionSession(
            "vision-1", "wss://evil.example/collect",
            "vision-token-123456", "2099-01-01T00:00:00Z"
        )).isAllowed());
    }

    @Test
    public void visualCredentialHasNoWebMessageSurface() {
        for (Method method : VisionSession.class.getDeclaredMethods()) {
            assertFalse("toWebMessage".equals(method.getName()));
        }
        ClientSession client = new ClientSession(
            "client-1", "once-secret", "robot-1",
            DigitalHumanSessionPolicy.BEIJING_FOUR_SERVER, "2099-01-01T00:00:00Z"
        );
        String webMessage = client.toWebMessage().toString();
        assertFalse(webMessage.contains("vision_token"));
        assertFalse(webMessage.contains("vision_session"));
    }
}
