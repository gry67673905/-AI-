package com.example.aicompanion.assistant;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.assistant.ChatContract.ChatError;
import com.example.aicompanion.assistant.ChatContract.ChatResponse;
import com.google.gson.Gson;

import org.junit.Test;

import java.util.concurrent.atomic.AtomicReference;

public class AssistantViewModelTest {
    @Test
    public void rejectsBlankAndOversizedMessagesWithoutCallingRepository() {
        FakeDataSource source = new FakeDataSource();
        AssistantViewModel viewModel = new AssistantViewModel(source);
        AtomicReference<ChatError> error = new AtomicReference<>();

        viewModel.submit("   ", errorsOnly(error));

        assertEquals("validation_error", error.get().getCode());
        assertFalse(source.called);

        error.set(null);
        viewModel.submit(repeat("政", 1001), errorsOnly(error));
        assertEquals("validation_error", error.get().getCode());
        assertFalse(source.called);
    }

    @Test
    public void carriesReturnedSessionIntoNextRequest() {
        FakeDataSource source = new FakeDataSource();
        source.autoResponse = response();
        AssistantViewModel viewModel = new AssistantViewModel(source);

        viewModel.submit("第一次", noOp());
        assertNull(source.lastSessionId);

        viewModel.submit("第二次", noOp());
        assertEquals("session-1", source.lastSessionId);
    }

    @Test
    public void rejectsSecondSubmissionWhileRequestIsInFlight() {
        FakeDataSource source = new FakeDataSource();
        AssistantViewModel viewModel = new AssistantViewModel(source);
        AtomicReference<ChatError> error = new AtomicReference<>();

        viewModel.submit("第一条", noOp());
        viewModel.submit("第二条", errorsOnly(error));

        assertTrue(source.called);
        assertEquals("request_in_progress", error.get().getCode());
    }

    private static ChatResponse response() {
        return new Gson().fromJson(GovAssistantRepositoryTest.successJson(), ChatResponse.class);
    }

    private static AssistantViewModel.UiCallback noOp() {
        return new AssistantViewModel.UiCallback() {
            @Override public void onSuccess(ChatResponse response) {}
            @Override public void onError(ChatError error) {}
        };
    }

    private static AssistantViewModel.UiCallback errorsOnly(AtomicReference<ChatError> error) {
        return new AssistantViewModel.UiCallback() {
            @Override public void onSuccess(ChatResponse response) {}
            @Override public void onError(ChatError value) { error.set(value); }
        };
    }

    private static String repeat(String value, int count) {
        StringBuilder output = new StringBuilder(count);
        for (int i = 0; i < count; i++) output.append(value);
        return output.toString();
    }

    private static final class FakeDataSource implements ChatDataSource {
        private boolean called;
        private String lastSessionId;
        private ChatResponse autoResponse;

        @Override
        public void sendChat(String sessionId, String message, Callback callback) {
            called = true;
            lastSessionId = sessionId;
            if (autoResponse != null) callback.onSuccess(autoResponse);
        }

        @Override
        public void cancelAll() {}
    }
}
