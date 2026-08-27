package com.example.aicompanion.navigation.business;

import com.example.aicompanion.navigation.engine.NavigationEngine;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.LocationSample;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RoutePreview;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RouteRequest;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.TravelMode;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.WindowOption;
import com.example.aicompanion.navigation.speech.NavigationSpeechOutput;

/** Coordinates a real or fake route engine without exposing Huawei SDK types to business code. */
public final class ServiceNavigationController implements NavigationEngine.Listener {
    private final NavigationEngine engine;
    private final NavigationSpeechOutput speech;
    private final NavigationStateMachine state = new NavigationStateMachine();
    private final Listener listener;
    private WindowOption selectedWindow;
    private TravelMode travelMode = TravelMode.WALKING;
    private RoutePreview preview;
    private boolean destroyed;

    public ServiceNavigationController(
        NavigationEngine engine,
        NavigationSpeechOutput speech,
        Listener listener
    ) {
        this.engine = engine;
        this.speech = speech;
        this.listener = listener;
        engine.setListener(this);
    }

    public NavigationStateMachine.Phase getPhase() { return state.getPhase(); }
    public WindowOption getSelectedWindow() { return selectedWindow; }
    public TravelMode getTravelMode() { return travelMode; }

    public void optionsReady() {
        state.optionsReady();
        publish();
    }

    public void selectWindow(WindowOption window) {
        if (destroyed || window == null) return;
        selectedWindow = window;
        preview = null;
        if (state.getPhase() == NavigationStateMachine.Phase.ERROR) state.recover();
        publish();
    }

    public void setTravelMode(TravelMode mode) {
        if (destroyed || mode == null) return;
        travelMode = mode;
        preview = null;
        if (state.getPhase() == NavigationStateMachine.Phase.ERROR) state.recover();
        publish();
    }

    public void plan(LocationSample origin) {
        if (destroyed) return;
        if (origin == null || selectedWindow == null) {
            fail("location_or_window_required", "请先取得前台定位并选择服务网点");
            return;
        }
        try {
            state.planning();
            preview = null;
            publish();
            engine.planRoute(new RouteRequest(origin, selectedWindow, travelMode));
        } catch (IllegalStateException invalid) {
            fail("invalid_navigation_state", "当前状态不能规划路线");
        }
    }

    public void updateLocation(LocationSample sample) {
        if (!destroyed && sample != null) engine.updateLocation(sample);
    }

    public void startNavigation() {
        if (destroyed || preview == null || state.getPhase() != NavigationStateMachine.Phase.PREVIEW) {
            fail("route_preview_required", "请先完成路线预览");
            return;
        }
        state.navigationStarting();
        publish();
        if (!engine.startNavigation()) {
            navigationStartFailed("navigation_start_rejected", "无法启动逐向导航");
        }
    }

    public void stopNavigation() {
        if (destroyed) return;
        engine.stopNavigation();
        speech.stop();
        if (state.getPhase() == NavigationStateMachine.Phase.STARTING_NAVIGATION
            || state.getPhase() == NavigationStateMachine.Phase.NAVIGATING) {
            state.navigationStopped();
            publish();
        }
    }

    public void destroy() {
        if (destroyed) return;
        destroyed = true;
        engine.stopNavigation();
        engine.destroy();
        speech.stop();
        speech.destroy();
        state.destroy();
        publish();
    }

    @Override public void onRouteReady(RoutePreview value) {
        if (destroyed || value == null || value.getPoints().size() < 2) return;
        preview = value;
        try {
            NavigationStateMachine.Phase phase = state.getPhase();
            if (phase == NavigationStateMachine.Phase.PLANNING) {
                state.previewReady();
            } else if (phase != NavigationStateMachine.Phase.NAVIGATING) {
                return;
            }
            if (listener != null) listener.onRoutePreview(value);
            publish();
        } catch (IllegalStateException ignored) {}
    }

    @Override public void onRouteFailure(String code, String message) {
        NavigationStateMachine.Phase phase = state.getPhase();
        if (phase == NavigationStateMachine.Phase.STARTING_NAVIGATION) {
            navigationStartFailed(code, message);
            return;
        }
        if (phase == NavigationStateMachine.Phase.NAVIGATING) {
            // A failed yaw/network recalculation is terminal for the current guidance session.
            // Stop the SDK and local TTS before publishing ERROR so no foreground listener or
            // stale instruction can survive while the user is offered a route retry.
            engine.stopNavigation();
            speech.stop();
        }
        fail(code, message);
    }

    @Override public void onNavigationInstruction(String text) {
        if (destroyed || state.getPhase() != NavigationStateMachine.Phase.NAVIGATING) return;
        speech.speak(text);
        if (listener != null) listener.onInstruction(text);
    }

    @Override public void onNavigationStarted() {
        if (destroyed || state.getPhase() != NavigationStateMachine.Phase.STARTING_NAVIGATION) return;
        state.navigationStarted();
        publish();
    }

    @Override public void onDestinationArrived() {
        if (destroyed) return;
        speech.speak("已到达目的地");
        if (state.getPhase() == NavigationStateMachine.Phase.NAVIGATING) {
            engine.stopNavigation();
            state.navigationStopped();
        }
        if (listener != null) listener.onArrived();
        publish();
    }

    private void fail(String code, String message) {
        if (destroyed) return;
        state.fail();
        if (listener != null) listener.onError(code, message);
        publish();
    }

    private void navigationStartFailed(String code, String message) {
        if (destroyed || state.getPhase() != NavigationStateMachine.Phase.STARTING_NAVIGATION) return;
        engine.stopNavigation();
        state.navigationStartFailed();
        if (listener != null) listener.onError(code, message);
        publish();
    }

    private void publish() {
        if (listener != null) listener.onPhaseChanged(state.getPhase());
    }

    public interface Listener {
        void onPhaseChanged(NavigationStateMachine.Phase phase);
        void onRoutePreview(RoutePreview preview);
        void onInstruction(String text);
        void onArrived();
        void onError(String code, String message);
    }
}
