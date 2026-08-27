package com.example.aicompanion.navigation.engine;

import com.example.aicompanion.navigation.model.ServiceNavigationContract.LocationSample;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RoutePreview;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RouteRequest;

/** SDK-free boundary around Huawei Navi Kit. */
public interface NavigationEngine {
    void setListener(Listener listener);
    void planRoute(RouteRequest request);
    boolean startNavigation();
    void updateLocation(LocationSample sample);
    void stopNavigation();
    void destroy();

    interface Listener {
        void onRouteReady(RoutePreview preview);
        void onRouteFailure(String code, String message);
        void onNavigationInstruction(String text);
        void onNavigationStarted();
        void onDestinationArrived();
    }
}
