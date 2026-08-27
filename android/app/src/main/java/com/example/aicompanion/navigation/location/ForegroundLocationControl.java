package com.example.aicompanion.navigation.location;

/** Android-free lifecycle boundary for foreground location collection. */
public interface ForegroundLocationControl {
    void startOneShot();
    void startContinuous();
    void stop();
}
