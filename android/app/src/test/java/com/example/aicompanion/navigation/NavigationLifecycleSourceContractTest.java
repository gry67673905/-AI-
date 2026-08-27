package com.example.aicompanion.navigation;

import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/** Guards lifecycle calls that cannot be executed against HMS classes in a host-side JVM. */
public class NavigationLifecycleSourceContractTest {
    @Test public void activityStopsTrackingAndNavigationOnStopAndDestroysThroughLifecycle() throws Exception {
        String source = read("src", "main", "java", "com", "example", "aicompanion",
            "ServiceNavigationActivity.java");
        assertTrue(source.contains("locationLifecycle.onStop();"));
        assertTrue(source.contains("locationLifecycle.destroy();"));
        assertTrue(source.contains("locationLifecycle.stopNavigation();"));
        assertTrue(source.contains("Phase.STARTING_NAVIGATION\n            || controller.getPhase()"));
        assertTrue(source.contains("stopButton.setEnabled(phase == NavigationStateMachine.Phase.STARTING_NAVIGATION"));
        assertTrue(source.contains("locationLifecycle.startNavigation(currentLocation)"));
        assertTrue(source.contains("演示路线，不用于实际出行"));
        assertTrue(source.contains("华为逐向导航已启动，等待首条导航提示"));
    }

    @Test public void oneShotFixRemovesUpdatesAndNaviDestroyRemovesListener() throws Exception {
        String location = read("src", "main", "java", "com", "example", "aicompanion",
            "navigation", "location", "ForegroundLocationSource.java");
        assertTrue(location.contains("mode == Mode.ONE_SHOT"));
        assertTrue(location.contains("client.removeLocationUpdates(callback);"));
        assertTrue(location.contains("if (!started || mode == Mode.IDLE) client.removeLocationUpdates(callback);"));
        assertTrue(location.contains("client.getLastLocation()"));
        assertTrue(location.contains("isUsableCachedLocation(location, System.currentTimeMillis())"));
        assertTrue(location.contains("MAX_CACHED_LOCATION_AGE_MILLIS"));
        assertTrue(location.contains("MAX_CACHED_LOCATION_ACCURACY_METERS"));
        assertTrue(!location.contains("无法取得最近定位"));

        String navi = read("src", "main", "java", "com", "example", "aicompanion",
            "navigation", "engine", "HuaweiNaviEngineAdapter.java");
        int remove = navi.indexOf("current.removeMapNaviListener(mapListener)");
        int destroy = navi.indexOf("current.destroy()", remove);
        assertTrue(remove >= 0);
        assertTrue(destroy > remove);
        assertTrue(navi.contains("initialized.setLocationContext(locationContext)"));
        assertTrue(navi.contains("updateExtraLocationData(location, -1d)"));
        assertTrue(navi.contains("case \"onStartNavi\""));
        assertTrue(navi.contains("case \"onDriveRoutesChanged\""));

        String speech = read("src", "main", "java", "com", "example", "aicompanion",
            "navigation", "speech", "AndroidNavigationSpeechOutput.java");
        assertTrue(speech.contains("TextToSpeech.LANG_MISSING_DATA"));
        assertTrue(speech.contains("TextToSpeech.LANG_NOT_SUPPORTED"));
    }

    private static String read(String... segments) throws Exception {
        return new String(Files.readAllBytes(Paths.get("", segments)), StandardCharsets.UTF_8);
    }
}
