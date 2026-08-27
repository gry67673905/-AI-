package com.example.aicompanion.navigation.speech;

/** Navigation-only speech output. It is never shared with the MetaStudio Activity. */
public interface NavigationSpeechOutput {
    void speak(String text);
    void stop();
    void destroy();
}
