package com.example.aicompanion.metastudio.business;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.JsonObject;

import org.junit.Test;

import java.time.Instant;
import java.util.Set;

public class DigitalHumanPoliciesTest {
    @Test
    public void networkPolicyAllowsOnlyLocalMainFrameAndPublishedHuaweiHosts() {
        DigitalHumanNetworkPolicy policy = new DigitalHumanNetworkPolicy();

        assertTrue(policy.isTrustedMainFrame(DigitalHumanNetworkPolicy.START_URL));
        assertFalse(policy.isTrustedMainFrame("https://metastudio-api.cn-north-4.myhuaweicloud.com/ics"));
        assertTrue(policy.isTrustedAsset(
            "https://digitalhuman.appassets.androidplatform.net/assets/metastudio/sdk/HwICSUiSdk.js"
        ));
        assertTrue(policy.isAllowedRemoteResource(
            "wss://metastudio-api.cn-north-4.myhuaweicloud.com/socket"
        ));
        assertTrue(policy.isAllowedRemoteResource(
            "https://metastudio-control.cn-southwest-2.myhuaweicloud.com/chat"
        ));
        assertTrue(policy.isAllowedRemoteResource(
            "wss://metastudio-control.cn-southwest-2.myhuaweicloud.com:443/chat"
        ));
        assertFalse(policy.isAllowedRemoteResource(
            "wss://metastudio-control.cn-southwest-2.myhuaweicloud.com:6447/chat"
        ));
        assertFalse(policy.isAllowedRemoteResource(
            "https://another.cn-southwest-2.myhuaweicloud.com/chat"
        ));
        assertFalse(policy.isAllowedRemoteResource(
            "wss://metastudio-control.cn-southwest-2.myhuaweicloud.com.evil.example/chat"
        ));
        assertTrue(policy.isAllowedRemoteResource("wss://rtc.example.dbankcdn.com:6447/session"));
        assertFalse(policy.isAllowedRemoteResource("wss://dbankcdn.com.evil.example/session"));
        assertFalse(policy.isAllowedRemoteResource("https://example.com/redirect"));
        assertFalse(policy.isAllowedRemoteResource("http://metastudio-api.cn-north-4.myhuaweicloud.com"));
        assertTrue(policy.isAllowedOrigin(DigitalHumanNetworkPolicy.APP_ORIGIN));
        assertTrue(policy.isAllowedOrigin(DigitalHumanNetworkPolicy.APP_ORIGIN + "/"));
        assertFalse(policy.isAllowedOrigin(DigitalHumanNetworkPolicy.APP_ORIGIN + "/path"));
        assertFalse(policy.isAllowedOrigin("https://user@" + DigitalHumanNetworkPolicy.APP_HOST + "/"));
    }

    @Test
    public void messagePolicyAcceptsOnlyFinalMinimalIntent() {
        DigitalHumanMessagePolicy policy = new DigitalHumanMessagePolicy();

        DigitalHumanMessagePolicy.Decision accepted = policy.validate(
            "{\"event\":\"semantic_final\",\"chat_id\":\"chat-1\",\"intent_id\":\"intent-1\",\"is_last\":true}"
        );
        assertTrue(accepted.isAllowed());
        assertEquals("intent-1", accepted.getSemanticIntent().getIntentId());
        assertFalse(policy.validate(
            "{\"event\":\"semantic_final\",\"chat_id\":\"chat-1\",\"intent_id\":\"intent-1\",\"is_last\":false}"
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"event\":\"semantic_final\",\"chat_id\":\"chat-1\",\"intent_id\":\"https://evil\",\"is_last\":true}"
        ).isAllowed());
        assertFalse(policy.validate("{\"event\":\"execute_native\"}").isAllowed());
    }

    @Test
    public void messagePolicyAcceptsOnlyFixedNonSensitiveSdkDiagnostics() {
        DigitalHumanMessagePolicy policy = new DigitalHumanMessagePolicy();

        assertTrue(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"ready_ws_client_6447\"}"
        ).isAllowed());
        assertTrue(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"csp_connect_rtc_443\"}"
        ).isAllowed());
        assertTrue(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"sdk_error_999200001\"}"
        ).isAllowed());
        assertTrue(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"sdk_error_4005\"}"
        ).isAllowed());
        assertTrue(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"sdk_error_mss_47015028\"}"
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"sdk_error_12345678\"}"
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"sdk_error_MSS.47010100\"}"
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"sdk_error_mss_12345678\"}"
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"event\":\"sdk_status\","
                + "\"status\":\"ready_ws_metastudio-client.cn-north-4.myhuaweicloud.com_6447\"}"
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"csp_connect_other_443?token=secret\"}"
        ).isAllowed());
        assertFalse(policy.validate(
            "{\"event\":\"sdk_status\",\"status\":\"sdk_error_999200001\","
                + "\"message\":\"wss://secret.example/path?token=value\"}"
        ).isAllowed());
        for (String kind : new String[]{"ready_ws", "csp_connect"}) {
            for (String host : new String[]{"meta", "client", "rtc", "huawei", "ip", "other"}) {
                for (String port : new String[]{"443", "6447", "other"}) {
                    String raw = "{\"event\":\"sdk_status\",\"status\":\""
                        + kind + "_" + host + "_" + port + "\"}";
                    assertTrue(raw, policy.validate(raw).isAllowed());
                }
            }
        }
    }

    @Test
    public void sdkDiagnosticsExposeOnlyWhitelistedCodesAndFriendlyCategories() {
        Set<String> statuses = DigitalHumanSdkDiagnostics.allowedErrorStatuses();

        assertTrue(statuses.contains("sdk_error_999200001"));
        assertTrue(statuses.contains("sdk_error_90100016"));
        assertTrue(statuses.contains("sdk_error_4005"));
        assertTrue(statuses.contains("sdk_error_mss_47015028"));
        assertFalse(statuses.contains("sdk_error_12345678"));
        assertTrue(DigitalHumanSdkDiagnostics.friendlyMessage("sdk_error_999200001")
            .startsWith("数字人 WebSocket 通道异常"));
        assertTrue(DigitalHumanSdkDiagnostics.friendlyMessage("sdk_error_90100005")
            .startsWith("数字人音频设备异常"));
        assertTrue(DigitalHumanSdkDiagnostics.friendlyMessage("sdk_error_mss_47015028")
            .startsWith("数字人 SIS 语音服务异常"));
        assertEquals(null, DigitalHumanSdkDiagnostics.friendlyMessage("sdk_error_12345678"));
        assertTrue(DigitalHumanSdkDiagnostics.isAllowedEndpointStatus("ready_ws_meta_443"));
        assertTrue(DigitalHumanSdkDiagnostics.isAllowedEndpointStatus("ready_ws_client_6447"));
        assertTrue(DigitalHumanSdkDiagnostics.isAllowedEndpointStatus("csp_connect_rtc_other"));
        assertTrue(DigitalHumanSdkDiagnostics.isAllowedEndpointStatus("csp_connect_huawei_443"));
        assertTrue(DigitalHumanSdkDiagnostics.isAllowedEndpointStatus("csp_connect_ip_6447"));
        assertFalse(DigitalHumanSdkDiagnostics.isAllowedEndpointStatus("ready_ws_evil_443"));
        assertFalse(DigitalHumanSdkDiagnostics.isAllowedEndpointStatus("csp_connect_other_443_token"));
        assertTrue(DigitalHumanSdkDiagnostics.friendlyMessage("ready_ws_client_6447")
            .contains("MetaStudio Client"));
        assertTrue(DigitalHumanSdkDiagnostics.friendlyMessage("csp_connect_other_443")
            .startsWith("数字人连接被 CSP 安全策略拦截"));
    }

    @Test
    public void sessionPolicyPinsBeijingFourHostWithoutUrlNormalization() {
        DigitalHumanSessionPolicy policy = new DigitalHumanSessionPolicy();
        assertTrue(policy.validate(new ClientSession(
            "session-1", "once-code-value", "robot_1",
            DigitalHumanSessionPolicy.BEIJING_FOUR_SERVER,
            Instant.now().plusSeconds(120).toString()
        )).isAllowed());
        assertFalse(policy.validate(new ClientSession(
            "session-1", "once-code-value", "robot_1",
            "https://" + DigitalHumanSessionPolicy.BEIJING_FOUR_SERVER,
            Instant.now().plusSeconds(120).toString()
        )).isAllowed());
        assertFalse(policy.validate(new ClientSession(
            "session-1", "once-code-value", "robot_1",
            "evil.example", Instant.now().plusSeconds(120).toString()
        )).isAllowed());
        assertFalse(policy.validate(new ClientSession(
            "session-1", "once-code-value", "robot_1",
            DigitalHumanSessionPolicy.BEIJING_FOUR_SERVER, "not-a-date"
        )).isAllowed());
        assertFalse(policy.validate(new ClientSession(
            "session-1", "once-code-value", "robot_1",
            DigitalHumanSessionPolicy.BEIJING_FOUR_SERVER,
            Instant.now().minusSeconds(1).toString()
        )).isAllowed());
    }

    @Test
    public void actionPolicyEnforcesRoleConfirmationAndPrefillAllowlist() {
        DigitalHumanActionPolicy policy = new DigitalHumanActionPolicy();
        JsonObject response = new JsonObject();
        response.addProperty("intent_id", "intent-1");
        response.addProperty("type", "OPEN_APPLICATION");
        response.addProperty("label", "查看我的办件");
        response.addProperty("section", "applications");
        response.addProperty("requires_confirmation", true);
        JsonObject prefill = new JsonObject();
        prefill.addProperty("application_id", "app-1");
        prefill.addProperty("url", "https://evil.example");
        response.add("prefill", prefill);

        DigitalHumanActionPolicy.Decision citizen = policy.validate(response, "intent-1", Role.CITIZEN);
        assertTrue(citizen.isAllowed());
        assertEquals("app-1", citizen.getIntent().getPrefill().get("application_id").getAsString());
        assertFalse(citizen.getIntent().getPrefill().has("url"));
        assertFalse(policy.validate(response, "intent-1", Role.ADMIN).isAllowed());

        response.addProperty("requires_confirmation", false);
        assertFalse(policy.validate(response, "intent-1", Role.CITIZEN).isAllowed());
        response.addProperty("requires_confirmation", true);
        assertFalse(policy.validate(response, "different-intent", Role.CITIZEN).isAllowed());
    }

    @Test
    public void semanticDeduplicatorUsesChatAndIntentPairAndStaysBounded() {
        SemanticIntentDeduplicator deduplicator = new SemanticIntentDeduplicator();
        assertTrue(deduplicator.accept("chat-1", "intent-1"));
        assertFalse(deduplicator.accept("chat-1", "intent-1"));
        assertTrue(deduplicator.accept("chat-2", "intent-1"));
        for (int i = 0; i < 300; i++) deduplicator.accept("chat-" + i, "intent-" + i);
        assertTrue(deduplicator.size() <= 256);
    }
}
