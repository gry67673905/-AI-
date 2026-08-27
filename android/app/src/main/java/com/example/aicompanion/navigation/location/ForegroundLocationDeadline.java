package com.example.aicompanion.navigation.location;

/** Android-free, cancellable first-fix timeout used by the foreground location source. */
public final class ForegroundLocationDeadline {
    public static final long DEFAULT_TIMEOUT_MILLIS = 10_000L;
    private final Scheduler scheduler;
    private Cancellable pending;

    public ForegroundLocationDeadline(Scheduler scheduler) {
        this.scheduler = scheduler;
    }

    public synchronized void start(Runnable timeout) {
        stop();
        pending = scheduler.schedule(() -> {
            synchronized (ForegroundLocationDeadline.this) { pending = null; }
            timeout.run();
        }, DEFAULT_TIMEOUT_MILLIS);
    }

    public synchronized void firstFixReceived() { stop(); }

    public synchronized void stop() {
        if (pending != null) pending.cancel();
        pending = null;
    }

    public interface Scheduler { Cancellable schedule(Runnable task, long delayMillis); }
    public interface Cancellable { void cancel(); }
}
