package com.example.aicompanion.portal;

import android.content.Context;

import com.example.aicompanion.BuildConfig;
import com.example.aicompanion.portal.business.PortalCommandPolicy;
import com.example.aicompanion.portal.business.SensitiveDisplayPolicy;
import com.example.aicompanion.portal.coordinator.AdminCoordinator;
import com.example.aicompanion.portal.coordinator.AuthCoordinator;
import com.example.aicompanion.portal.coordinator.CitizenCoordinator;
import com.example.aicompanion.portal.coordinator.PortalCoordinatorViewModel;
import com.example.aicompanion.portal.coordinator.StaffTaskCoordinator;
import com.example.aicompanion.portal.coordinator.VoiceConsultationCoordinator;
import com.example.aicompanion.portal.gateway.BrokeredSecureSessionStore;
import com.example.aicompanion.portal.gateway.CatalogGateway;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.MaterialDocumentGateway;
import com.example.aicompanion.portal.gateway.OkHttpAdminGateway;
import com.example.aicompanion.portal.gateway.OkHttpApplicationGateway;
import com.example.aicompanion.portal.gateway.OkHttpAuthGateway;
import com.example.aicompanion.portal.gateway.OkHttpCatalogGateway;
import com.example.aicompanion.portal.gateway.OkHttpStaffGateway;
import com.example.aicompanion.portal.gateway.OkHttpStreamingGateway;

/** Application-scoped dependency graph; keeps construction out of Activity business code. */
public final class PortalGraph {
    private static volatile PortalGraph instance;
    private final NativeApiClient api;
    private final CatalogGateway catalogGateway;
    private final MaterialDocumentGateway materialDocumentGateway;
    private final PortalCoordinatorViewModel.Factory viewModelFactory;

    private PortalGraph(Context context) {
        BrokeredSecureSessionStore store = new BrokeredSecureSessionStore(context);
        api = new NativeApiClient(NativeApiClient.defaultClient(), BuildConfig.GOV_API_BASE, store);
        materialDocumentGateway = new MaterialDocumentGateway(api, context.getCacheDir());
        OkHttpAuthGateway authGateway = new OkHttpAuthGateway(api);
        OkHttpCatalogGateway catalog = new OkHttpCatalogGateway(api);
        OkHttpApplicationGateway applications = new OkHttpApplicationGateway(api, context.getContentResolver());
        OkHttpStreamingGateway streaming = new OkHttpStreamingGateway(api);
        OkHttpStaffGateway staff = new OkHttpStaffGateway(api);
        OkHttpAdminGateway admin = new OkHttpAdminGateway(api, context.getContentResolver());
        catalogGateway = catalog;
        viewModelFactory = new PortalCoordinatorViewModel.Factory(
            new AuthCoordinator(authGateway),
            new CitizenCoordinator(catalog, applications, streaming),
            new StaffTaskCoordinator(staff),
            new AdminCoordinator(admin),
            new VoiceConsultationCoordinator(streaming),
            new PortalCommandPolicy(),
            new SensitiveDisplayPolicy(),
            api
        );
    }

    public static PortalGraph create(Context context) {
        PortalGraph current = instance;
        if (current != null) return current;
        synchronized (PortalGraph.class) {
            if (instance == null) instance = new PortalGraph(context.getApplicationContext());
            return instance;
        }
    }

    public PortalCoordinatorViewModel.Factory viewModelFactory() { return viewModelFactory; }
    public CatalogGateway catalogGateway() { return catalogGateway; }
    public MaterialDocumentGateway materialDocumentGateway() { return materialDocumentGateway; }
}
