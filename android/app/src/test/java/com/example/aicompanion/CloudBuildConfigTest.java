package com.example.aicompanion;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class CloudBuildConfigTest {
    private static final String CLOUD_API = "https://123.249.68.176";

    @Test
    public void cloudDemoVersionAndApiOriginArePinned() {
        assertEquals(2, BuildConfig.VERSION_CODE);
        assertEquals("0.2.0-cloud-demo", BuildConfig.VERSION_NAME);
        assertEquals(CLOUD_API, BuildConfig.GOV_API_BASE);
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
}
