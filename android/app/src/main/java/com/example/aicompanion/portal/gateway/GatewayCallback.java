package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;

public interface GatewayCallback<T> {
    void onSuccess(T value);
    void onError(ApiFailure error);
}
