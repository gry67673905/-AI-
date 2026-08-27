package com.example.aicompanion.portal.boundary;

import android.webkit.JavascriptInterface;

import java.lang.ref.WeakReference;

/** Narrow entry categories. There is no generic native method or network URL entrypoint. */
public final class PortalJsBoundary {
    public interface Host {
        void executeCommand(String envelopeJson);
        void chooseDocument(String requestJson);
        void controlVoice(String action);
        void openServiceNavigation(String serviceId);
        void saveGeneratedDocument(String generationId);
    }

    private final WeakReference<Host> host;

    public PortalJsBoundary(Host host) {
        this.host = new WeakReference<>(host);
    }

    @JavascriptInterface
    public void execute(String envelopeJson) {
        Host target = host.get();
        if (target != null) target.executeCommand(envelopeJson);
    }

    @JavascriptInterface
    public void chooseDocument(String requestJson) {
        Host target = host.get();
        if (target != null) target.chooseDocument(requestJson);
    }

    @JavascriptInterface
    public void voice(String action) {
        Host target = host.get();
        if (target != null) target.controlVoice(action);
    }

    @JavascriptInterface
    public void openServiceNavigation(String serviceId) {
        Host target = host.get();
        if (target != null) target.openServiceNavigation(serviceId);
    }

    @JavascriptInterface
    public void saveGeneratedDocument(String generationId) {
        Host target = host.get();
        if (target != null) target.saveGeneratedDocument(generationId);
    }
}
