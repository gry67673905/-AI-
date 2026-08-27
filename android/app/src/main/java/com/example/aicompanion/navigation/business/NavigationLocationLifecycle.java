package com.example.aicompanion.navigation.business;

import com.example.aicompanion.navigation.location.ForegroundLocationControl;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.LocationSample;

/**
 * Coordinates the two allowed location phases: one fix for local sorting, then continuous fixes
 * only while the user-confirmed turn-by-turn navigation is active.
 */
public final class NavigationLocationLifecycle {
    private final ForegroundLocationControl location;
    private final ServiceNavigationController navigation;
    private final Listener listener;
    private boolean destroyed;

    public NavigationLocationLifecycle(
        ForegroundLocationControl location,
        ServiceNavigationController navigation,
        Listener listener
    ) {
        this.location = location;
        this.navigation = navigation;
        this.listener = listener;
    }

    public boolean requestSortFix(boolean permissionGranted) {
        if (destroyed) return false;
        if (!permissionGranted) {
            if (listener != null) listener.onPermissionRequired();
            return false;
        }
        location.stop();
        location.startOneShot();
        return true;
    }

    public void permissionDenied() {
        if (!destroyed && listener != null) listener.onPermissionDenied();
    }

    public boolean startNavigation(LocationSample latestLocation) {
        if (destroyed || latestLocation == null
            || navigation.getPhase() != NavigationStateMachine.Phase.PREVIEW) return false;
        location.stop();
        location.startContinuous();
        navigation.updateLocation(latestLocation);
        navigation.startNavigation();
        NavigationStateMachine.Phase phase = navigation.getPhase();
        boolean accepted = phase == NavigationStateMachine.Phase.STARTING_NAVIGATION
            || phase == NavigationStateMachine.Phase.NAVIGATING;
        if (!accepted) location.stop();
        return accepted;
    }

    public void stopNavigation() {
        if (destroyed) return;
        location.stop();
        navigation.stopNavigation();
    }

    public void stopTracking() {
        if (!destroyed) location.stop();
    }

    public void onStop() { stopNavigation(); }

    public void destroy() {
        if (destroyed) return;
        location.stop();
        navigation.destroy();
        destroyed = true;
    }

    public interface Listener {
        void onPermissionRequired();
        void onPermissionDenied();
    }
}
