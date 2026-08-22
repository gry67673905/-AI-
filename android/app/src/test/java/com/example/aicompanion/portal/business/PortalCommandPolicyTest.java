package com.example.aicompanion.portal.business;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.Role;

import org.junit.Test;

public class PortalCommandPolicyTest {
    private final PortalCommandPolicy policy = new PortalCommandPolicy();

    @Test
    public void allowsKnownPublicCommandAndParsesTypedEnvelope() {
        PortalCommandPolicy.Decision result = policy.validate(
            "{\"request_id\":\"web-1\",\"command\":\"CATALOG_SEARCH\",\"payload\":{\"query\":\"社保\"}}",
            Role.ANONYMOUS
        );

        assertTrue(result.isAllowed());
        assertEquals(Command.CATALOG_SEARCH, result.getEnvelope().getCommand());
    }

    @Test
    public void roleMatrixRejectsPrivilegeEscalation() {
        PortalCommandPolicy.Decision result = policy.validate(
            "{\"request_id\":\"web-2\",\"command\":\"STAFF_APPROVE\",\"payload\":{\"application_id\":\"app-1\"}}",
            Role.CITIZEN
        );

        assertFalse(result.isAllowed());
        assertEquals("forbidden", result.getCode());
    }

    @Test
    public void rejectsUrlHttpAndNativeMethodInjection() {
        for (String key : new String[]{"url", "http_method", "native_method", "class_name"}) {
            PortalCommandPolicy.Decision result = policy.validate(
                "{\"request_id\":\"web-3\",\"command\":\"CATALOG_SEARCH\",\"payload\":{\"" + key + "\":\"https://evil.invalid\"}}",
                Role.ANONYMOUS
            );
            assertFalse(key, result.isAllowed());
            assertEquals("invalid_payload", result.getCode());
        }
    }

    @Test
    public void validatesResourceIdAndChatLength() {
        PortalCommandPolicy.Decision badId = policy.validate(
            "{\"request_id\":\"web-4\",\"command\":\"CATALOG_DETAILS\",\"payload\":{\"service_id\":\"../secret\"}}",
            Role.ANONYMOUS
        );
        assertFalse(badId.isAllowed());

        StringBuilder message = new StringBuilder();
        for (int i = 0; i < 1001; i++) message.append('政');
        PortalCommandPolicy.Decision tooLong = policy.validate(
            "{\"request_id\":\"web-5\",\"command\":\"CHAT_STREAM\",\"payload\":{\"message\":\"" + message + "\"}}",
            Role.ANONYMOUS
        );
        assertFalse(tooLong.isAllowed());
    }

    @Test
    public void cancelAndKnowledgeCommandsEnforceRoleAndSafeIdentifiers() {
        assertTrue(policy.validate(envelope("PAYMENT_CANCEL", "payment_id", "pay-1"), Role.CITIZEN).isAllowed());
        assertTrue(policy.validate(envelope("DELIVERY_CANCEL", "delivery_id", "delivery-1"), Role.CITIZEN).isAllowed());
        assertTrue(policy.validate(envelope("HANDOFF_CANCEL", "ticket_id", "ticket-1"), Role.CITIZEN).isAllowed());
        assertTrue(policy.validate(envelope("ADMIN_KNOWLEDGE_RETRY", "job_id", "job-1"), Role.ADMIN).isAllowed());
        assertTrue(policy.validate(envelope("ADMIN_KNOWLEDGE_ARCHIVE", "job_id", "job-1"), Role.ADMIN).isAllowed());

        assertFalse(policy.validate(envelope("ADMIN_KNOWLEDGE_RETRY", "job_id", "job-1"), Role.CITIZEN).isAllowed());
        assertFalse(policy.validate(envelope("ADMIN_KNOWLEDGE_ARCHIVE", "job_id", "../job"), Role.ADMIN).isAllowed());
    }

    private static String envelope(String command, String key, String value) {
        return "{\"request_id\":\"web-new\",\"command\":\"" + command
            + "\",\"payload\":{\"" + key + "\":\"" + value + "\"}}";
    }
}
