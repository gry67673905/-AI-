package com.example.aicompanion.portal.coordinator;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import androidx.arch.core.executor.testing.InstantTaskExecutorRule;
import androidx.lifecycle.Observer;

import com.example.aicompanion.portal.business.PortalCommandPolicy;
import com.example.aicompanion.portal.business.SensitiveDisplayPolicy;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.OkHttpAdminGateway;
import com.example.aicompanion.portal.gateway.OkHttpApplicationGateway;
import com.example.aicompanion.portal.gateway.OkHttpAuthGateway;
import com.example.aicompanion.portal.gateway.OkHttpCatalogGateway;
import com.example.aicompanion.portal.gateway.OkHttpStaffGateway;
import com.example.aicompanion.portal.gateway.OkHttpStreamingGateway;
import com.example.aicompanion.portal.gateway.SecureSessionStore;
import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UiState;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.Gson;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;

public class PortalCoordinatorViewModelTest {
    @Rule public final InstantTaskExecutorRule instantTaskExecutorRule = new InstantTaskExecutorRule();

    private MockWebServer server;
    private NativeApiClient api;
    private PortalCoordinatorViewModel viewModel;
    private MemorySessionStore store;

    @Before
    public void setUp() {
        server = new MockWebServer();
        store = new MemorySessionStore();
        api = new NativeApiClient(new OkHttpClient(), server.url("/").toString(), store);
        OkHttpAuthGateway auth = new OkHttpAuthGateway(api);
        OkHttpCatalogGateway catalog = new OkHttpCatalogGateway(api);
        OkHttpStreamingGateway streaming = new OkHttpStreamingGateway(api);
        viewModel = new PortalCoordinatorViewModel(
            new AuthCoordinator(auth),
            new CitizenCoordinator(catalog, new OkHttpApplicationGateway(api, null), streaming),
            new StaffTaskCoordinator(new OkHttpStaffGateway(api)),
            new AdminCoordinator(new OkHttpAdminGateway(api, null)),
            new VoiceConsultationCoordinator(streaming),
            new PortalCommandPolicy(),
            new SensitiveDisplayPolicy(),
            api
        );
    }

    @After
    public void tearDown() throws Exception {
        api.cancelAll();
        server.shutdown();
    }

    @Test
    public void loginStateIsObservableAfterObserverRecreationWithoutSecrets() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json").setBody(
            "{\"access_token\":\"never-webview\",\"refresh_token\":\"never-webview-refresh\",\"user\":{\"id\":\"u1\",\"display_name\":\"演示群众\",\"role\":\"CITIZEN\",\"applicant_type\":\"INDIVIDUAL\"}}"
        ));
        CountDownLatch completed = new CountDownLatch(1);
        Observer<UiState> firstObserver = state -> {
            if ("AUTH_LOGIN".equals(state.getCommand()) && "success".equals(state.getPhase())) completed.countDown();
        };
        viewModel.state().observeForever(firstObserver);

        viewModel.executeBridgeCommand("{\"request_id\":\"login-1\",\"command\":\"AUTH_LOGIN\",\"payload\":{\"username\":\"demo\",\"password\":\"demo-password\"}}");

        assertTrue(completed.await(3, TimeUnit.SECONDS));
        assertEquals(Role.CITIZEN, viewModel.currentRole());
        viewModel.state().removeObserver(firstObserver);

        AtomicReference<UiState> recreated = new AtomicReference<>();
        Observer<UiState> recreatedObserver = recreated::set;
        viewModel.state().observeForever(recreatedObserver);
        assertNotNull(recreated.get());
        assertEquals("success", recreated.get().getPhase());
        String serialized = new Gson().toJson(recreated.get());
        assertFalse(serialized.contains("never-webview"));
        viewModel.state().removeObserver(recreatedObserver);
    }

    @Test
    public void nativePolicyBlocksCitizenOnlyCommandForAnonymousUser() {
        viewModel.executeBridgeCommand("{\"request_id\":\"staff-1\",\"command\":\"STAFF_TASKS\",\"payload\":{}}");

        UiState state = viewModel.state().getValue();
        assertNotNull(state);
        assertEquals("error", state.getPhase());
        assertEquals("forbidden", state.getError().getCode());
    }

    @Test
    public void binaryDownload401UsesUnifiedSessionReset() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json").setBody(
            "{\"access_token\":\"expired-access\",\"refresh_token\":\"refresh-secret\","
                + "\"user\":{\"id\":\"u1\",\"display_name\":\"演示群众\",\"role\":\"CITIZEN\","
                + "\"applicant_type\":\"INDIVIDUAL\"}}"
        ));
        CountDownLatch loggedIn = new CountDownLatch(1);
        Observer<UiState> observer = state -> {
            if ("AUTH_LOGIN".equals(state.getCommand()) && "success".equals(state.getPhase())) {
                loggedIn.countDown();
            }
        };
        viewModel.state().observeForever(observer);
        viewModel.executeBridgeCommand(
            "{\"request_id\":\"login-download\",\"command\":\"AUTH_LOGIN\","
                + "\"payload\":{\"username\":\"demo\",\"password\":\"demo-password\"}}"
        );
        assertTrue(loggedIn.await(3, TimeUnit.SECONDS));
        assertTrue(store.load().isAuthenticated());

        viewModel.handleBoundaryApiFailure(
            "MATERIAL_DOCUMENT_DOWNLOAD",
            new ApiFailure(401, "authentication_required", "请重新登录")
        );

        UiState state = viewModel.state().getValue();
        assertNotNull(state);
        assertEquals("MATERIAL_DOCUMENT_DOWNLOAD", state.getCommand());
        assertEquals("error", state.getPhase());
        assertEquals(Role.ANONYMOUS, viewModel.currentRole());
        assertFalse(store.load().isAuthenticated());
        viewModel.state().removeObserver(observer);
    }

    @Test
    public void newChatClearsRememberedSessionWithoutNetworkWrite() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "text/event-stream")
            .setBody("event: meta\ndata: {\"session_id\":\"session-1\"}\n\n"
                + "event: delta\ndata: {\"text\":\"您好\"}\n\n"
                + "event: done\ndata: {\"session_id\":\"session-1\"}\n\n"));
        CountDownLatch completed = new CountDownLatch(1);
        Observer<UiState> observer = state -> {
            if ("CHAT_STREAM".equals(state.getCommand()) && "success".equals(state.getPhase())) {
                completed.countDown();
            }
        };
        viewModel.state().observeForever(observer);
        viewModel.executeBridgeCommand(
            "{\"request_id\":\"chat-1\",\"command\":\"CHAT_STREAM\",\"payload\":{\"message\":\"你好\"}}"
        );
        assertTrue(completed.await(3, TimeUnit.SECONDS));
        assertEquals("session-1", viewModel.currentChatSessionId());

        viewModel.executeBridgeCommand(
            "{\"request_id\":\"reset-1\",\"command\":\"CHAT_SESSION_RESET\",\"payload\":{}}"
        );
        assertEquals("", viewModel.currentChatSessionId());
        assertEquals("CHAT_SESSION_RESET", viewModel.state().getValue().getCommand());
        viewModel.state().removeObserver(observer);
    }

    @Test
    public void newChatCannotResetWhileStreamIsStillInFlight() {
        server.enqueue(new MockResponse().setHeadersDelay(5, TimeUnit.SECONDS)
            .setResponseCode(200).setHeader("Content-Type", "text/event-stream")
            .setBody("event: done\ndata: {}\n\n"));
        viewModel.executeBridgeCommand(
            "{\"request_id\":\"chat-slow\",\"command\":\"CHAT_STREAM\",\"payload\":{\"message\":\"慢请求\"}}"
        );

        viewModel.executeBridgeCommand(
            "{\"request_id\":\"reset-busy\",\"command\":\"CHAT_SESSION_RESET\",\"payload\":{}}"
        );

        UiState state = viewModel.state().getValue();
        assertNotNull(state);
        assertEquals("CHAT_SESSION_RESET", state.getCommand());
        assertEquals("error", state.getPhase());
        assertEquals("request_in_progress", state.getError().getCode());
    }

    @Test
    public void incompleteStreamReleasesCoordinatorForExplicitRetry() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "text/event-stream")
            .setBody("event: delta\ndata: {\"text\":\"半条回答\"}\n\n"));
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "text/event-stream")
            .setBody("event: delta\ndata: {\"text\":\"完整回答\"}\n\n"
                + "event: done\ndata: {\"answer\":\"完整回答\"}\n\n"));
        CountDownLatch failed = new CountDownLatch(1);
        CountDownLatch retried = new CountDownLatch(1);
        Observer<UiState> observer = state -> {
            if ("chat-first".equals(state.getRequestId()) && "error".equals(state.getPhase())) {
                failed.countDown();
            }
            if ("chat-retry".equals(state.getRequestId()) && "success".equals(state.getPhase())) {
                retried.countDown();
            }
        };
        viewModel.state().observeForever(observer);

        viewModel.executeBridgeCommand(
            "{\"request_id\":\"chat-first\",\"command\":\"CHAT_STREAM\",\"payload\":{\"message\":\"原问题\"}}"
        );
        assertTrue(failed.await(3, TimeUnit.SECONDS));
        viewModel.executeBridgeCommand(
            "{\"request_id\":\"chat-retry\",\"command\":\"CHAT_STREAM\",\"payload\":{\"message\":\"原问题\"}}"
        );

        assertTrue(retried.await(3, TimeUnit.SECONDS));
        assertEquals("chat-retry", viewModel.state().getValue().getRequestId());
        viewModel.state().removeObserver(observer);
    }

    private static final class MemorySessionStore implements SecureSessionStore {
        private Snapshot snapshot = Snapshot.empty();
        @Override public Snapshot load() { return snapshot; }
        @Override public void save(SessionSecrets secrets, UserProfile profile) { snapshot = new Snapshot(secrets, profile); }
        @Override public void clear() { snapshot = Snapshot.empty(); }
    }
}
