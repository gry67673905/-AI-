package com.example.aicompanion.portal.coordinator;

import com.example.aicompanion.portal.gateway.ApplicationGateway;
import com.example.aicompanion.portal.gateway.CatalogGateway;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.StreamingGateway;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.EnumSet;

/** Coordinates public catalog and authenticated citizen cases without UI dependencies. */
public final class CitizenCoordinator {
    private static final EnumSet<Command> CATALOG = EnumSet.of(
        Command.CATALOG_SEARCH, Command.CATALOG_DETAILS, Command.ELIGIBILITY_CHECK,
        Command.MATERIALS_GET, Command.PROCESS_GET, Command.FORM_SCHEMA_GET, Command.WINDOW_LIST
    );
    private static final EnumSet<Command> CONSULTATIONS = EnumSet.of(
        Command.CONSULTATION_HISTORY, Command.CONSULTATION_FEEDBACK,
        Command.HANDOFF_CREATE, Command.HANDOFF_MESSAGES, Command.HANDOFF_MESSAGE_ADD,
        Command.HANDOFF_CANCEL
    );

    private final CatalogGateway catalog;
    private final ApplicationGateway applications;
    private final StreamingGateway consultations;

    public CitizenCoordinator(CatalogGateway catalog, ApplicationGateway applications, StreamingGateway consultations) {
        this.catalog = catalog;
        this.applications = applications;
        this.consultations = consultations;
    }

    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        if (CATALOG.contains(command)) {
            catalog.execute(command, payload, callback);
        } else if (CONSULTATIONS.contains(command)) {
            consultations.executeConsultation(command, payload, callback);
        } else {
            applications.execute(command, payload, callback);
        }
    }

    public void uploadMaterial(SelectedDocument document, GatewayCallback<JsonElement> callback) {
        applications.uploadMaterial(document, callback);
    }
}
