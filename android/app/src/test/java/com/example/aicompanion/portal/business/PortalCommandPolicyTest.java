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

    @Test
    public void materialDocumentCommandsAreCitizenOnlyAndBounded() {
        assertTrue(policy.validate(
            envelope("MATERIAL_TEMPLATE_OPTIONS_GET", "application_id", "app-1"),
            Role.CITIZEN
        ).isAllowed());
        assertFalse(policy.validate(
            envelope("MATERIAL_TEMPLATE_OPTIONS_GET", "application_id", "app-1"),
            Role.ANONYMOUS
        ).isAllowed());
        String generate = "{\"request_id\":\"material-1\",\"command\":\"MATERIAL_TEMPLATE_GENERATE\","
            + "\"payload\":{\"application_id\":\"app-1\",\"requirement_code\":\"id-2\","
            + "\"template_id\":\"template-1\",\"request_text\":\"请预填联系人\"}}";
        assertTrue(policy.validate(generate, Role.CITIZEN).isAllowed());
        assertFalse(policy.validate(generate, Role.ANONYMOUS).isAllowed());
        assertFalse(policy.validate(generate.replace("template-1", "../template"), Role.CITIZEN).isAllowed());

        StringBuilder longText = new StringBuilder();
        for (int index = 0; index < 301; index++) longText.append('字');
        assertFalse(policy.validate(generate.replace("请预填联系人", longText), Role.CITIZEN).isAllowed());
        assertTrue(policy.validate(
            envelope("MATERIAL_TEMPLATE_STATUS_GET", "generation_id", "generation-1"),
            Role.CITIZEN
        ).isAllowed());
    }

    @Test
    public void consultationHistoryAndMaterialIntentCommandsStayNarrow() {
        assertTrue(policy.validate(
            envelope("CONSULTATION_MESSAGES", "session_id", "session-1"),
            Role.CITIZEN
        ).isAllowed());
        assertFalse(policy.validate(
            envelope("CONSULTATION_MESSAGES", "session_id", "session-1"),
            Role.ANONYMOUS
        ).isAllowed());
        String confirm = "{\"request_id\":\"intent-1\",\"command\":\"CONSULTATION_MATERIAL_CONFIRM\","
            + "\"payload\":{\"session_id\":\"session-1\",\"intent_id\":\"intent-1\"}}";
        assertTrue(policy.validate(confirm, Role.CITIZEN).isAllowed());
        assertFalse(policy.validate(confirm.replace("intent-1\"}", "../intent\"}"), Role.CITIZEN).isAllowed());
        assertTrue(policy.validate(
            "{\"request_id\":\"reset-1\",\"command\":\"CHAT_SESSION_RESET\",\"payload\":{}}",
            Role.ANONYMOUS
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"request_id\":\"reset-2\",\"command\":\"CHAT_SESSION_RESET\",\"payload\":{\"session_id\":\"session-1\"}}",
            Role.ANONYMOUS
        ).isAllowed());
        assertTrue(policy.validate(
            "{\"request_id\":\"history-1\",\"command\":\"CONSULTATION_HISTORY\",\"payload\":{\"limit\":\"20\"}}",
            Role.CITIZEN
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"request_id\":\"history-2\",\"command\":\"CONSULTATION_HISTORY\",\"payload\":{\"limit\":\"101\"}}",
            Role.CITIZEN
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"request_id\":\"messages-2\",\"command\":\"CONSULTATION_MESSAGES\",\"payload\":{\"session_id\":\"session-1\",\"before\":\"../message\"}}",
            Role.CITIZEN
        ).isAllowed());
    }

    private static String envelope(String command, String key, String value) {
        return "{\"request_id\":\"web-new\",\"command\":\"" + command
            + "\",\"payload\":{\"" + key + "\":\"" + value + "\"}}";
    }
}
