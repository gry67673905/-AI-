package com.example.aicompanion.navigation.gateway;

import com.example.aicompanion.navigation.model.ServiceNavigationContract.NavigationOptions;
import com.example.aicompanion.portal.gateway.GatewayCallback;

public interface NavigationOptionsGateway {
    void load(String serviceId, GatewayCallback<NavigationOptions> callback);
}
