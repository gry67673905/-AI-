package com.example.aicompanion.portal.gateway;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okhttp3.mockwebserver.Dispatcher;
import okio.Buffer;

public class MaterialDocumentGatewayTest {
    @Rule public final TemporaryFolder temporary = new TemporaryFolder();

    private MockWebServer server;
    private MemorySessionStore store;
    private MaterialDocumentGateway gateway;

    @Before public void setUp() {
        server = new MockWebServer();
        store = new MemorySessionStore();
        store.save(new SessionSecrets("access-secret", "refresh-secret", "Bearer"),
            new UserProfile("u1", "演示群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        NativeApiClient api = new NativeApiClient(new OkHttpClient(), server.url("/").toString(), store);
        gateway = new MaterialDocumentGateway(api, temporary.getRoot());
    }

    @After public void tearDown() throws Exception { server.shutdown(); }

    @Test public void downloadsOnlyFixedAuthenticatedDocxAndValidatesPackage() throws Exception {
        byte[] bytes = minimalDocx();
        String sha = sha256(bytes);
        server.enqueue(new MockResponse().setResponseCode(200)
            .setHeader("Content-Type", MaterialDocumentGateway.DOCX_MIME)
            .setHeader("X-Content-SHA256", sha)
            .setHeader("Content-Disposition", "attachment; filename*=UTF-8''%E4%B8%A2%E5%A4%B1%E8%AF%B4%E6%98%8E.docx")
            .setBody(new Buffer().write(bytes)));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<MaterialDocumentGateway.CachedDocument> result = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        gateway.download("generation-1", callback(latch, result, failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(failure.get());
        assertNotNull(result.get());
        assertTrue(result.get().getFile().isFile());
        assertEquals("丢失说明.docx", result.get().getDisplayName());
        assertEquals(sha, result.get().getSha256());
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals("/api/v1/material-documents/generation-1/download", request.getPath());
        assertEquals("Bearer access-secret", request.getHeader("Authorization"));
        assertEquals(MaterialDocumentGateway.DOCX_MIME, request.getHeader("Accept"));
        assertNull(request.getRequestUrl().query());
    }

    @Test public void rejectsWrongMimeAndDoesNotFollowRedirect() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200)
            .setHeader("Content-Type", "text/html")
            .setHeader("X-Content-SHA256", "0000000000000000000000000000000000000000000000000000000000000000")
            .setBody("not a docx"));
        CountDownLatch first = new CountDownLatch(1);
        AtomicReference<ApiFailure> firstFailure = new AtomicReference<>();
        gateway.download("generation-2", callback(first, new AtomicReference<>(), firstFailure));
        assertTrue(first.await(3, TimeUnit.SECONDS));
        assertEquals("invalid_document_mime", firstFailure.get().getCode());

        server.enqueue(new MockResponse().setResponseCode(302).setHeader("Location", "/untrusted"));
        CountDownLatch second = new CountDownLatch(1);
        AtomicReference<ApiFailure> secondFailure = new AtomicReference<>();
        gateway.download("generation-3", callback(second, new AtomicReference<>(), secondFailure));
        assertTrue(second.await(3, TimeUnit.SECONDS));
        assertNotNull(secondFailure.get());
        server.takeRequest(1, TimeUnit.SECONDS);
        server.takeRequest(1, TimeUnit.SECONDS);
        assertNull(server.takeRequest(150, TimeUnit.MILLISECONDS));
    }

    @Test public void filenameCannotEscapeOrChangeDocumentType() {
        assertEquals("evil.pdf.docx", MaterialDocumentGateway.safeFilename(
            "attachment; filename=\"../../evil.pdf\"", "generation-4"
        ));
        String fallback = MaterialDocumentGateway.safeFilename("", "generation-4");
        assertTrue(fallback.endsWith(".docx"));
        assertFalse(fallback.contains("/"));
        assertFalse(fallback.contains("\\"));
    }

    @Test public void preservesUnauthorizedStatusForUnifiedSessionReset() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(401)
            .setHeader("Content-Type", "application/json")
            .setBody("{\"code\":\"authentication_required\",\"message\":\"请重新登录\"}"));
        CountDownLatch completed = new CountDownLatch(1);
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        gateway.download("generation-expired", callback(
            completed, new AtomicReference<>(), failure
        ));

        assertTrue(completed.await(3, TimeUnit.SECONDS));
        assertNotNull(failure.get());
        assertEquals(401, failure.get().getStatusCode());
        assertEquals("authentication_required", failure.get().getCode());
    }

    @Test public void dropsValidatedCacheWhenLoggedInOwnerChangesDuringDownload() throws Exception {
        byte[] bytes = minimalDocx();
        String sha = sha256(bytes);
        CountDownLatch observed = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        server.setDispatcher(new Dispatcher() {
            @Override public MockResponse dispatch(RecordedRequest request) throws InterruptedException {
                observed.countDown();
                release.await(2, TimeUnit.SECONDS);
                return new MockResponse().setResponseCode(200)
                    .setHeader("Content-Type", MaterialDocumentGateway.DOCX_MIME)
                    .setHeader("X-Content-SHA256", sha)
                    .setBody(new Buffer().write(bytes));
            }
        });
        CountDownLatch completed = new CountDownLatch(1);
        AtomicReference<ApiFailure> failure = new AtomicReference<>();
        gateway.download("generation-owner-change", callback(
            completed, new AtomicReference<>(), failure
        ));
        assertTrue(observed.await(2, TimeUnit.SECONDS));
        store.save(new SessionSecrets("other-access", "other-refresh", "Bearer"),
            new UserProfile("u2", "另一群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        release.countDown();

        assertTrue(completed.await(3, TimeUnit.SECONDS));
        assertNotNull(failure.get());
        assertEquals("session_changed", failure.get().getCode());
        File cache = new File(temporary.getRoot(), "generated-material-documents");
        File[] remaining = cache.listFiles();
        assertTrue(remaining == null || remaining.length == 0);
    }

    private static GatewayCallback<MaterialDocumentGateway.CachedDocument> callback(
        CountDownLatch latch,
        AtomicReference<MaterialDocumentGateway.CachedDocument> result,
        AtomicReference<ApiFailure> failure
    ) {
        return new GatewayCallback<MaterialDocumentGateway.CachedDocument>() {
            @Override public void onSuccess(MaterialDocumentGateway.CachedDocument value) {
                result.set(value);
                latch.countDown();
            }
            @Override public void onError(ApiFailure error) {
                failure.set(error);
                latch.countDown();
            }
        };
    }

    private static byte[] minimalDocx() throws Exception {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(bytes)) {
            add(zip, "[Content_Types].xml", "<Types/>");
            add(zip, "word/document.xml", "<w:document/>");
        }
        return bytes.toByteArray();
    }

    private static void add(ZipOutputStream zip, String name, String content) throws Exception {
        zip.putNextEntry(new ZipEntry(name));
        zip.write(content.getBytes(StandardCharsets.UTF_8));
        zip.closeEntry();
    }

    private static String sha256(byte[] bytes) throws Exception {
        StringBuilder output = new StringBuilder(64);
        for (byte item : MessageDigest.getInstance("SHA-256").digest(bytes)) {
            output.append(String.format(Locale.ROOT, "%02x", item & 0xff));
        }
        return output.toString();
    }

    private static final class MemorySessionStore implements SecureSessionStore {
        private Snapshot snapshot = Snapshot.empty();
        @Override public Snapshot load() { return snapshot; }
        @Override public void save(SessionSecrets secrets, UserProfile profile) {
            snapshot = new Snapshot(secrets, profile);
        }
        @Override public void clear() { snapshot = Snapshot.empty(); }
    }
}
