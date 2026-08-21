package com.example.aicompanion.assistant;

import com.example.aicompanion.assistant.ChatContract.ChatError;
import com.example.aicompanion.assistant.ChatContract.ChatResponse;

public interface ChatDataSource {
    void sendChat(String sessionId, String message, Callback callback);

    void cancelAll();

    interface Callback {
        void onSuccess(ChatResponse response);

        void onError(ChatError error);
    }
}
