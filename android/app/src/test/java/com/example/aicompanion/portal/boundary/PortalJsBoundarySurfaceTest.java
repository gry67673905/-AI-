package com.example.aicompanion.portal.boundary;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

public class PortalJsBoundarySurfaceTest {
    @Test public void bridgeExposesServiceNavigationButNoWindowCoordinateOrUrlEntry() {
        Set<String> methods = Arrays.stream(PortalJsBoundary.class.getDeclaredMethods())
            .filter(method -> java.lang.reflect.Modifier.isPublic(method.getModifiers()))
            .map(Method::getName)
            .collect(Collectors.toSet());
        assertTrue(methods.contains("openServiceNavigation"));
        assertTrue(methods.contains("saveGeneratedDocument"));
        assertFalse(methods.contains("openWindowMap"));
        assertFalse(methods.contains("openUrl"));
        assertFalse(methods.contains("openCoordinates"));
        assertFalse(methods.contains("downloadUrl"));
        assertFalse(methods.contains("saveDocumentUrl"));
    }

    @Test public void portalUsesTypedMaterialCommandsAndGenerationIdOnlySaveBridge() throws Exception {
        String source = new String(Files.readAllBytes(
            Paths.get("src", "main", "assets", "portal-app-v2.js")
        ), StandardCharsets.UTF_8);
        assertTrue(source.contains("invoke('MATERIAL_TEMPLATE_GENERATE'"));
        assertTrue(source.contains("invoke('MATERIAL_TEMPLATE_STATUS_GET'"));
        assertTrue(source.contains("nativeBridge.saveGeneratedDocument(requiredValue('material-generation-id'"));
        assertFalse(source.contains("saveGeneratedDocument({"));
        assertFalse(source.contains("material-documents/"));
    }

    @Test public void materialPollingIsBoundedAndTemplateSelectionTracksApplication() throws Exception {
        String source = new String(Files.readAllBytes(
            Paths.get("src", "main", "assets", "portal-app-v2.js")
        ), StandardCharsets.UTF_8);
        String policy = new String(Files.readAllBytes(
            Paths.get("src", "main", "assets", "material-poll-policy.js")
        ), StandardCharsets.UTF_8);
        assertTrue(policy.contains("MAX_TOTAL_MS = 5 * 60 * 1000"));
        assertTrue(source.contains("materialPollPolicy.canPoll"));
        assertTrue(source.contains("自动刷新已暂停"));
        assertTrue(source.contains("bindClick('material-generation-refresh'"));
        assertTrue(source.contains("resetMaterialPollWindow();"));
        assertTrue(source.contains("byId('application-id').addEventListener('input'"));
        assertTrue(source.contains("clearMaterialTemplateSelection(true);"));
    }

    @Test public void navigationActivityUsesForegroundPermissionOnlyAndIsNotExported() throws Exception {
        String manifest = new String(Files.readAllBytes(
            Paths.get("src", "main", "AndroidManifest.xml")
        ), StandardCharsets.UTF_8);
        assertTrue(manifest.contains("android.permission.ACCESS_FINE_LOCATION"));
        assertTrue(manifest.contains("android.permission.ACCESS_COARSE_LOCATION"));
        assertFalse(manifest.contains("android.permission.ACCESS_BACKGROUND_LOCATION"));
        int activity = manifest.indexOf("android:name=\".ServiceNavigationActivity\"");
        assertTrue(activity >= 0);
        String declaration = manifest.substring(activity, manifest.indexOf("/>", activity));
        assertTrue(declaration.contains("android:exported=\"false\""));
        assertFalse(manifest.contains("android.permission.READ_EXTERNAL_STORAGE"));
        assertFalse(manifest.contains("android.permission.WRITE_EXTERNAL_STORAGE"));
        assertFalse(manifest.contains("androidx.core.content.FileProvider"));
    }
}
