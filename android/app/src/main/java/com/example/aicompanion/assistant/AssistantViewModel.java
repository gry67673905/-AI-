package com.example.aicompanion.assistant;

import androidx.annotation.NonNull;
import androidx.lifecycle.ViewModel;
import androidx.lifecycle.ViewModelProvider;

import com.example.aicompanion.assistant.ChatContract.ChatError;
import com.example.aicompanion.assistant.ChatContract.ChatResponse;

/** Keeps the anonymous backend session across Activity recreation. */
public final class AssistantViewModel extends ViewModel {
    private static final int MAX_MESSAGE_CODE_POINTS = 1000;

    private final ChatDataSource dataSource;
    private final Object lock = new Object();
    private String sessionId;
    private boolean requestInFlight;

    public AssistantViewModel(ChatDataSource dataSource) {
        this.dataSource = dataSource;
    }

    public void submit(String rawMessage, UiCallback callback) {
        String message = rawMessage == null ? "" : rawMessage.trim();
        int length = message.codePointCount(0, message.length());
        if (length == 0 || length > MAX_MESSAGE_CODE_POINTS) {
            callback.onError(new ChatError(
                0,
                "validation_error",
                length == 0 ? "请输入政务问题" : "问题不能超过 1000 个字符"
            ));
            return;
        }

        String currentSession;
        synchronized (lock) {
            if (requestInFlight) {
                callback.onError(new ChatError(0, "request_in_progress", "上一条问题仍在处理中"));
                return;
            }
            requestInFlight = true;
            currentSession = sessionId;
        }

        dataSource.sendChat(currentSession, message, new ChatDataSource.Callback() {
            @Override
            public void onSuccess(ChatResponse response) {
                synchronized (lock) {
                    requestInFlight = false;
                    sessionId = response.getSessionId();
                }
                callback.onSuccess(response);
            }

            @Override
            public void onError(ChatError error) {
                synchronized (lock) {
                    requestInFlight = false;
                }
                callback.onError(error);
            }
        });
    }

    @Override
    protected void onCleared() {
        dataSource.cancelAll();
    }

    public interface UiCallback {
        void onSuccess(ChatResponse response);

        void onError(ChatError error);
    }

    public static final class Factory implements ViewModelProvider.Factory {
        private final ChatDataSource dataSource;

        public Factory(ChatDataSource dataSource) {
            this.dataSource = dataSource;
        }

        @NonNull
        @Override
        @SuppressWarnings("unchecked")
        public <T extends ViewModel> T create(@NonNull Class<T> modelClass) {
            if (!modelClass.isAssignableFrom(AssistantViewModel.class)) {
                throw new IllegalArgumentException("Unknown ViewModel class: " + modelClass.getName());
            }
            return (T) new AssistantViewModel(dataSource);
        }
    }
}
