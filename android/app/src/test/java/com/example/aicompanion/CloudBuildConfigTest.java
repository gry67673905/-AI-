package com.example.aicompanion;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.example.aicompanion.metastudio.business.DigitalHumanSdkDiagnostics;

public class CloudBuildConfigTest {
    private static final String CLOUD_API = "https://123.249.68.176";

    @Test
    public void cloudDeviceTestVersionAndApiOriginArePinned() {
        assertEquals(7, BuildConfig.VERSION_CODE);
        assertEquals("0.3.0-material-docgen-test", BuildConfig.VERSION_NAME);
        assertEquals(CLOUD_API, BuildConfig.GOV_API_BASE);
        assertEquals("5.0.6", BuildConfig.METASTUDIO_SDK_VERSION);
        assertEquals(
            "d8d028588b35580856d8cc1fc35b67b50fbc8f99525c45ea5d990feec86c7641",
            BuildConfig.METASTUDIO_SDK_ARCHIVE_SHA256
        );
        assertTrue(BuildConfig.METASTUDIO_SDK_READY);
    }

    @Test
    public void cloudBuildHasNoCleartextOrPlaceholderFallback() {
        assertTrue(BuildConfig.GOV_API_BASE.startsWith("https://"));
        assertFalse(BuildConfig.GOV_API_BASE.startsWith("http://"));
        assertFalse(BuildConfig.GOV_API_BASE.contains("10.0.2.2"));
        assertFalse(BuildConfig.GOV_API_BASE.contains("127.0.0.1"));
        assertFalse(BuildConfig.GOV_API_BASE.contains("localhost"));
        assertFalse(BuildConfig.GOV_API_BASE.contains("api.invalid"));
    }

    @Test
    public void metaStudioWrapperBindsOpaqueClientSessionWithoutAccountSecrets() throws Exception {
        Path wrapper = Paths.get("src", "main", "assets", "metastudio", "app.js");
        String source = new String(Files.readAllBytes(wrapper), StandardCharsets.UTF_8);

        assertTrue(source.contains(
            "extendParamStr: JSON.stringify({client_id: String(session.session_id)})"
        ));
        assertFalse(source.contains("Authorization: Bearer"));
        assertFalse(source.contains("access_token"));
        assertFalse(source.contains("refresh_token"));
        assertFalse(source.contains("huawei_secret"));
        assertTrue(source.contains("jobInfoChange"));
        assertTrue(source.contains("job.isReady === true"));
        assertFalse(source.contains("await window.HwICSUiSdk.create(launch);\n            launch.onceCode = '';\n            status('ready')"));
    }

    @Test
    public void metaStudioWrapperObservesStreamingAsrWithoutForwardingTranscript() throws Exception {
        Path wrapper = Paths.get("src", "main", "assets", "metastudio", "app.js");
        String source = new String(Files.readAllBytes(wrapper), StandardCharsets.UTF_8);

        assertTrue(source.contains("speechRecognized: (question) => observeSpeechRecognition(question)"));
        assertTrue(source.contains("if (!conversationActive"));
        assertTrue(source.contains("Number.isSafeInteger(resultId)"));
        assertTrue(source.contains("typeof isLast !== 'boolean'"));
        assertTrue(source.contains("typeof question.text !== 'string'"));
        assertTrue(source.contains("status('asr_partial')"));
        assertTrue(source.contains("status('asr_final')"));
        assertTrue(source.contains("renderSpeechCaption(chatId, resultId, question.text, isLast)"));
        assertTrue(source.contains("document.getElementById('local-caption-text').textContent = text"));
        assertTrue(source.contains("interactionPhase === PHASE.ANSWERING"));
        assertTrue(source.contains("status('ready')"));
        assertTrue(source.contains("enableCaption: true"));
        assertTrue(source.contains("enableCollectAudioDemand: false"));
        assertTrue(source.contains("enableVadInterrupt: true"));
        assertFalse(source.contains("MAX_RESULT_ID"));
        assertFalse(source.contains("speechState.lastResultId"));
        assertFalse(source.contains("post(question"));
        assertFalse(source.contains("JSON.stringify(question"));
        assertFalse(source.contains("console.log(question"));
    }

    @Test
    public void metaStudioCaptionFallbackStaysInsideIsolatedWrapper() throws Exception {
        Path page = Paths.get("src", "main", "assets", "metastudio", "index.html");
        Path styles = Paths.get("src", "main", "assets", "metastudio", "style.css");
        String html = new String(Files.readAllBytes(page), StandardCharsets.UTF_8);
        String css = new String(Files.readAllBytes(styles), StandardCharsets.UTF_8);

        assertTrue(html.contains("id=\"local-caption\""));
        assertTrue(html.contains("id=\"local-caption-text\""));
        assertTrue(html.contains("aria-live=\"polite\""));
        assertTrue(css.contains("#local-caption"));
        assertTrue(css.contains("pointer-events: none"));
    }

    @Test
    public void metaStudioWrapperReportsOnlyFixedSdkCodesAndPortCategories() throws Exception {
        Path wrapper = Paths.get("src", "main", "assets", "metastudio", "app.js");
        String source = new String(Files.readAllBytes(wrapper), StandardCharsets.UTF_8);
        Matcher matcher = Pattern.compile("'sdk_error_([0-9]+)'").matcher(source);
        Set<String> wrapperStatuses = new HashSet<>();
        while (matcher.find()) wrapperStatuses.add("sdk_error_" + matcher.group(1));

        Set<String> expected = new HashSet<>(DigitalHumanSdkDiagnostics.allowedErrorStatuses());
        expected.remove("sdk_error_unknown");
        expected.removeIf(status -> status.startsWith("sdk_error_mss_"));
        assertEquals(expected, wrapperStatuses);
        assertTrue(source.contains("Object.prototype.hasOwnProperty.call(error, 'code')"));
        assertTrue(source.contains("error.errorCode"));
        assertTrue(source.contains("/^MSS\\.[0-9]{8}$/"));
        assertTrue(source.contains("'47015028'"));
        assertTrue(source.contains("`sdk_error_mss_${suffix}`"));
        assertFalse(source.contains("error.message"));
        assertFalse(source.contains("error.errorMsg"));
        assertFalse(source.contains("JSON.stringify(error"));
        assertTrue(source.contains("hasExplicitScheme ? address : `wss://${address}`"));
        assertTrue(source.contains("metastudio-client.cn-north-4.myhuaweicloud.com"));
        assertTrue(source.contains("window.addEventListener('securitypolicyviolation'"));
        assertTrue(source.contains("event.effectiveDirective !== 'connect-src'"));
        assertTrue(source.contains("`ready_ws_${safeEndpointCategory(address)}`"));
        assertTrue(source.contains("`csp_connect_${safeEndpointCategory(address)}`"));
        assertFalse(source.contains("status(job.websocketAddr"));
        assertFalse(source.contains("status(event.blockedURI"));
        assertFalse(source.contains("post(event"));
    }

    @Test
    public void metaStudioCspAllowsOnlySdkRequiredWorkletWasmAndRtcPort() throws Exception {
        Path page = Paths.get("src", "main", "assets", "metastudio", "index.html");
        String source = new String(Files.readAllBytes(page), StandardCharsets.UTF_8);

        assertTrue(source.contains("script-src 'self' data: 'wasm-unsafe-eval'"));
        assertFalse(source.contains("'unsafe-eval'"));
        assertTrue(source.contains("worker-src 'self' blob: data:"));
        assertTrue(source.contains("wss://*.hicloud.com:6447"));
        assertTrue(source.contains("https://*.dbankcdn.com:6447"));
        String controlHost = "metastudio-control.cn-southwest-2.myhuaweicloud.com";
        String connect = source.substring(
            source.indexOf("connect-src "),
            source.indexOf("; media-src ")
        );
        assertTrue(connect.contains("https://" + controlHost));
        assertTrue(connect.contains("wss://" + controlHost));
        assertFalse(connect.contains(controlHost + ":6447"));
        assertFalse(source.contains("*.myhuaweicloud.com"));
        assertEquals(2, occurrences(source, controlHost));
    }

    private static int occurrences(String source, String needle) {
        int count = 0;
        int index = 0;
        while ((index = source.indexOf(needle, index)) >= 0) {
            count++;
            index += needle.length();
        }
        return count;
    }
}
