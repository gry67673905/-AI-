package com.example.aicompanion.navigation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.navigation.business.NavigationStateMachine;
import com.example.aicompanion.navigation.business.NavigationLocationLifecycle;
import com.example.aicompanion.navigation.business.NearbyWindowSelector;
import com.example.aicompanion.navigation.business.ServiceIdPolicy;
import com.example.aicompanion.navigation.business.ServiceNavigationController;
import com.example.aicompanion.navigation.engine.NavigationEngine;
import com.example.aicompanion.navigation.location.ForegroundLocationDeadline;
import com.example.aicompanion.navigation.location.ForegroundLocationControl;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.GeoPoint;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.LocationSample;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RoutePreview;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RouteRequest;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.TravelMode;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.WindowOption;
import com.example.aicompanion.navigation.speech.NavigationSpeechOutput;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

public class ServiceNavigationBusinessTest {
    private static final String SERVICE_ID = "11111111-1111-4111-8111-111111111111";

    @Test public void serviceBoundaryAcceptsOnlyCanonicalUuid() {
        ServiceIdPolicy policy = new ServiceIdPolicy();
        assertEquals(SERVICE_ID, policy.normalize(SERVICE_ID));
        assertNull(policy.normalize(" " + SERVICE_ID));
        assertNull(policy.normalize("aaaaaaaa-1111-4111-8111-111111111111".toUpperCase(java.util.Locale.ROOT)));
        assertNull(policy.normalize("svc-1"));
        assertNull(policy.normalize("https://example.test/" + SERVICE_ID));
    }

    @Test public void nearbySelectorKeepsThreeNearestLocallyAndFallsBackToPriority() {
        WindowOption near = window("11111111-1111-4111-8111-111111111112", "近", 30.0005, 120.0005, 9);
        WindowOption middle = window("11111111-1111-4111-8111-111111111113", "中", 30.01, 120.01, 1);
        WindowOption far = window("11111111-1111-4111-8111-111111111114", "远", 31.0, 121.0, 0);
        WindowOption fourth = window("11111111-1111-4111-8111-111111111115", "第四", 32.0, 122.0, 2);
        NearbyWindowSelector selector = new NearbyWindowSelector();

        List<WindowOption> nearest = selector.select(
            Arrays.asList(far, fourth, middle, near), new GeoPoint(30, 120), 3
        );
        assertEquals(Arrays.asList(near.getId(), middle.getId(), far.getId()), Arrays.asList(
            nearest.get(0).getId(), nearest.get(1).getId(), nearest.get(2).getId()
        ));
        assertEquals(far.getId(), selector.select(Arrays.asList(near, middle, far), null, 3).get(0).getId());
    }

    @Test public void fakeEngineVerifiesWalkDefaultSpeechStopAndDestroy() {
        FakeEngine engine = new FakeEngine();
        FakeSpeech speech = new FakeSpeech();
        RecordingListener listener = new RecordingListener();
        ServiceNavigationController controller = new ServiceNavigationController(engine, speech, listener);
        WindowOption destination = window(
            "11111111-1111-4111-8111-111111111112", "服务中心", 30.1, 120.1, 1
        );

        assertEquals(TravelMode.WALKING, controller.getTravelMode());
        controller.setTravelMode(TravelMode.DRIVING);
        controller.optionsReady();
        controller.selectWindow(destination);
        controller.plan(location(30, 120));

        assertEquals(TravelMode.DRIVING, engine.request.getMode());
        assertEquals(NavigationStateMachine.Phase.PREVIEW, controller.getPhase());
        controller.startNavigation();
        engine.emitInstruction("前方左转");
        assertEquals("前方左转", speech.lastSpoken);
        assertEquals(NavigationStateMachine.Phase.NAVIGATING, controller.getPhase());

        controller.stopNavigation();
        assertTrue(engine.stopCalls > 0);
        assertTrue(speech.stopCalls > 0);
        controller.destroy();
        assertTrue(engine.destroyed);
        assertTrue(speech.destroyed);
        assertEquals(NavigationStateMachine.Phase.DESTROYED, controller.getPhase());
    }

    @Test public void routeFailureEntersErrorCanRetryAndNeverStartsEarly() {
        FakeEngine engine = new FakeEngine();
        FakeSpeech speech = new FakeSpeech();
        NonThrowingListener listener = new NonThrowingListener();
        ServiceNavigationController controller = new ServiceNavigationController(engine, speech, listener);
        controller.optionsReady();
        controller.selectWindow(window(
            "11111111-1111-4111-8111-111111111112", "服务中心", 30.1, 120.1, 1
        ));
        engine.failNextPlan = true;

        controller.plan(location(30, 120));

        assertEquals(NavigationStateMachine.Phase.ERROR, controller.getPhase());
        assertEquals(0, engine.startCalls);
        assertEquals("route_failed", listener.lastErrorCode);

        controller.plan(location(30, 120));
        assertEquals(NavigationStateMachine.Phase.PREVIEW, controller.getPhase());
        assertEquals(0, engine.startCalls);
        controller.startNavigation();
        assertEquals(1, engine.startCalls);
    }

    @Test public void navigationWaitsForAsyncSuccessAndAsyncFailureReturnsToPreview() {
        FakeEngine engine = new FakeEngine();
        engine.autoStartCallback = false;
        FakeSpeech speech = new FakeSpeech();
        NonThrowingListener listener = new NonThrowingListener();
        ServiceNavigationController controller = new ServiceNavigationController(engine, speech, listener);
        controller.optionsReady();
        controller.selectWindow(window(
            "11111111-1111-4111-8111-111111111112", "服务中心", 30.1, 120.1, 1
        ));
        controller.plan(location(30, 120));

        controller.startNavigation();
        assertEquals(NavigationStateMachine.Phase.STARTING_NAVIGATION, controller.getPhase());
        engine.emitInstruction("不应提前播报");
        assertNull(speech.lastSpoken);

        engine.emitStartSuccess();
        assertEquals(NavigationStateMachine.Phase.NAVIGATING, controller.getPhase());
        controller.stopNavigation();
        assertEquals(NavigationStateMachine.Phase.PREVIEW, controller.getPhase());

        controller.startNavigation();
        assertEquals(NavigationStateMachine.Phase.STARTING_NAVIGATION, controller.getPhase());
        engine.emitStartFailure(17);
        assertEquals(NavigationStateMachine.Phase.PREVIEW, controller.getPhase());
        assertEquals("navigation_start_failed_17", listener.lastErrorCode);
        assertTrue(engine.stopCalls > 0);
    }

    @Test public void failedRecalculationStopsGuidanceAndSpeechBeforeError() {
        FakeEngine engine = new FakeEngine();
        FakeSpeech speech = new FakeSpeech();
        NonThrowingListener listener = new NonThrowingListener();
        ServiceNavigationController controller = new ServiceNavigationController(engine, speech, listener);
        controller.optionsReady();
        controller.selectWindow(window(
            "11111111-1111-4111-8111-111111111112", "服务中心", 30.1, 120.1, 1
        ));
        controller.plan(location(30, 120));
        controller.startNavigation();
        int stopCallsBeforeFailure = engine.stopCalls;
        int speechStopsBeforeFailure = speech.stopCalls;

        engine.emitRouteFailure("route_recalculation_failed");

        assertEquals(NavigationStateMachine.Phase.ERROR, controller.getPhase());
        assertEquals(stopCallsBeforeFailure + 1, engine.stopCalls);
        assertEquals(speechStopsBeforeFailure + 1, speech.stopCalls);
        assertEquals("route_recalculation_failed", listener.lastErrorCode);
    }

    @Test public void firstFixDeadlineIsExplicitAndCancellable() {
        FakeScheduler scheduler = new FakeScheduler();
        ForegroundLocationDeadline deadline = new ForegroundLocationDeadline(scheduler);
        AtomicBoolean timedOut = new AtomicBoolean();

        deadline.start(() -> timedOut.set(true));
        assertEquals(ForegroundLocationDeadline.DEFAULT_TIMEOUT_MILLIS, scheduler.delay);
        deadline.firstFixReceived();
        scheduler.run();
        assertFalse(timedOut.get());

        deadline.start(() -> timedOut.set(true));
        scheduler.run();
        assertTrue(timedOut.get());
    }

    @Test public void locationLifecycleSeparatesSortFixNavigationAndCleanup() {
        FakeEngine engine = new FakeEngine();
        FakeSpeech speech = new FakeSpeech();
        NonThrowingListener navigationListener = new NonThrowingListener();
        ServiceNavigationController controller = new ServiceNavigationController(
            engine, speech, navigationListener
        );
        FakeLocationControl tracker = new FakeLocationControl();
        FakePermissionListener permissions = new FakePermissionListener();
        NavigationLocationLifecycle lifecycle = new NavigationLocationLifecycle(
            tracker, controller, permissions
        );

        assertFalse(lifecycle.requestSortFix(false));
        assertEquals(1, permissions.required);
        assertEquals(0, tracker.oneShotStarts);
        lifecycle.permissionDenied();
        assertEquals(1, permissions.denied);

        assertTrue(lifecycle.requestSortFix(true));
        assertEquals(1, tracker.oneShotStarts);
        assertEquals(0, tracker.continuousStarts);

        controller.optionsReady();
        controller.selectWindow(window(
            "11111111-1111-4111-8111-111111111112", "服务中心", 30.1, 120.1, 1
        ));
        controller.plan(location(30, 120));
        assertEquals(NavigationStateMachine.Phase.PREVIEW, controller.getPhase());

        LocationSample latest = location(30, 120);
        assertTrue(lifecycle.startNavigation(latest));
        assertEquals(1, tracker.continuousStarts);
        assertEquals(1, engine.startCalls);
        assertTrue(engine.locationPresentAtStart);
        assertEquals(latest, engine.lastLocation);
        lifecycle.onStop();
        assertTrue(tracker.stopCalls >= 3);
        assertTrue(engine.stopCalls > 0);

        lifecycle.destroy();
        assertTrue(engine.destroyed);
        assertTrue(speech.destroyed);
    }

    private static WindowOption window(String id, String name, double lat, double lon, int priority) {
        return new WindowOption(id, "W", name, "地址", "09:00-17:00", new GeoPoint(lat, lon),
            "GCJ02", priority, "DEMO", "CN", "seed", "2026-08-25T00:00:00Z");
    }

    private static LocationSample location(double lat, double lon) {
        return new LocationSample(new GeoPoint(lat, lon), 5f, 0f, 0f, 1L);
    }

    private static final class FakeEngine implements NavigationEngine {
        Listener listener;
        RouteRequest request;
        int stopCalls;
        int startCalls;
        LocationSample lastLocation;
        boolean locationPresentAtStart;
        boolean failNextPlan;
        boolean autoStartCallback = true;
        boolean destroyed;
        @Override public void setListener(Listener listener) { this.listener = listener; }
        @Override public void planRoute(RouteRequest request) {
            this.request = request;
            if (failNextPlan) {
                failNextPlan = false;
                listener.onRouteFailure("route_failed", "规划失败");
                return;
            }
            listener.onRouteReady(new RoutePreview(1200, 600, Arrays.asList(
                request.getOrigin().getPoint(), request.getDestination().getPoint()
            )));
        }
        @Override public boolean startNavigation() {
            startCalls++;
            locationPresentAtStart = lastLocation != null;
            if (autoStartCallback) listener.onNavigationStarted();
            return true;
        }
        @Override public void updateLocation(LocationSample sample) { lastLocation = sample; }
        @Override public void stopNavigation() { stopCalls++; }
        @Override public void destroy() { destroyed = true; }
        void emitInstruction(String text) { listener.onNavigationInstruction(text); }
        void emitStartSuccess() { listener.onNavigationStarted(); }
        void emitStartFailure(int code) {
            listener.onRouteFailure(
                "navigation_start_failed_" + code,
                "华为导航启动失败"
            );
        }
        void emitRouteFailure(String code) { listener.onRouteFailure(code, "路线重算失败"); }
    }

    private static final class FakeSpeech implements NavigationSpeechOutput {
        String lastSpoken;
        int stopCalls;
        boolean destroyed;
        @Override public void speak(String text) { lastSpoken = text; }
        @Override public void stop() { stopCalls++; }
        @Override public void destroy() { destroyed = true; }
    }

    private static final class RecordingListener implements ServiceNavigationController.Listener {
        @Override public void onPhaseChanged(NavigationStateMachine.Phase phase) {}
        @Override public void onRoutePreview(RoutePreview preview) {}
        @Override public void onInstruction(String text) {}
        @Override public void onArrived() {}
        @Override public void onError(String code, String message) { throw new AssertionError(message); }
    }

    private static final class NonThrowingListener implements ServiceNavigationController.Listener {
        String lastErrorCode;
        @Override public void onPhaseChanged(NavigationStateMachine.Phase phase) {}
        @Override public void onRoutePreview(RoutePreview preview) {}
        @Override public void onInstruction(String text) {}
        @Override public void onArrived() {}
        @Override public void onError(String code, String message) { lastErrorCode = code; }
    }

    private static final class FakeScheduler implements ForegroundLocationDeadline.Scheduler {
        Runnable task;
        long delay;
        boolean cancelled;
        @Override public ForegroundLocationDeadline.Cancellable schedule(Runnable task, long delayMillis) {
            this.task = task;
            this.delay = delayMillis;
            this.cancelled = false;
            return () -> cancelled = true;
        }
        void run() { if (!cancelled && task != null) task.run(); }
    }

    private static final class FakeLocationControl implements ForegroundLocationControl {
        int oneShotStarts;
        int continuousStarts;
        int stopCalls;
        @Override public void startOneShot() { oneShotStarts++; }
        @Override public void startContinuous() { continuousStarts++; }
        @Override public void stop() { stopCalls++; }
    }

    private static final class FakePermissionListener implements NavigationLocationLifecycle.Listener {
        int required;
        int denied;
        @Override public void onPermissionRequired() { required++; }
        @Override public void onPermissionDenied() { denied++; }
    }
}
