package com.example.aicompanion.navigation.business;

/** Small explicit state machine; route planning or navigation cannot be started out of order. */
public final class NavigationStateMachine {
    public enum Phase {
        LOADING_OPTIONS,
        READY,
        PLANNING,
        PREVIEW,
        STARTING_NAVIGATION,
        NAVIGATING,
        ERROR,
        DESTROYED
    }

    private Phase phase = Phase.LOADING_OPTIONS;
    private Phase recoverable = Phase.LOADING_OPTIONS;

    public synchronized Phase getPhase() { return phase; }

    public synchronized void optionsReady() { require(Phase.LOADING_OPTIONS, Phase.ERROR); set(Phase.READY); }
    public synchronized void planning() { require(Phase.READY, Phase.PREVIEW, Phase.ERROR); set(Phase.PLANNING); }
    public synchronized void previewReady() { require(Phase.PLANNING); set(Phase.PREVIEW); }
    public synchronized void navigationStarting() {
        require(Phase.PREVIEW);
        set(Phase.STARTING_NAVIGATION);
    }
    public synchronized void navigationStarted() {
        require(Phase.STARTING_NAVIGATION);
        set(Phase.NAVIGATING);
    }
    public synchronized void navigationStartFailed() {
        require(Phase.STARTING_NAVIGATION);
        set(Phase.PREVIEW);
    }
    public synchronized void navigationStopped() {
        require(Phase.STARTING_NAVIGATION, Phase.NAVIGATING);
        set(Phase.PREVIEW);
    }
    public synchronized void fail() {
        if (phase == Phase.DESTROYED) return;
        recoverable = phase == Phase.PLANNING ? Phase.READY
            : phase == Phase.STARTING_NAVIGATION ? Phase.PREVIEW : phase;
        phase = Phase.ERROR;
    }
    public synchronized void recover() {
        require(Phase.ERROR);
        phase = recoverable == Phase.DESTROYED ? Phase.READY : recoverable;
    }
    public synchronized void destroy() { phase = Phase.DESTROYED; recoverable = Phase.DESTROYED; }

    private void set(Phase next) { phase = next; recoverable = next; }
    private void require(Phase... allowed) {
        for (Phase candidate : allowed) if (phase == candidate) return;
        throw new IllegalStateException("Invalid navigation transition from " + phase);
    }
}
