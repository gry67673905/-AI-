package com.example.aicompanion.metastudio;

import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

public final class DigitalHumanManifestTest {
    @Test
    public void declaresBothWebRtcAudioPermissions() throws Exception {
        Path manifest = Paths.get("src", "main", "AndroidManifest.xml");
        String xml = new String(Files.readAllBytes(manifest), StandardCharsets.UTF_8);

        assertTrue(xml.contains("android.permission.RECORD_AUDIO"));
        assertTrue(xml.contains("android.permission.MODIFY_AUDIO_SETTINGS"));
    }
}
