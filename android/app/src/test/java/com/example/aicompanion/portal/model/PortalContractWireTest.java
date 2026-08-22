package com.example.aicompanion.portal.model;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Source;
import com.example.aicompanion.portal.model.PortalContract.ToolCall;
import com.google.gson.Gson;
import com.google.gson.JsonObject;

import org.junit.Test;

public class PortalContractWireTest {
    private final Gson gson = new Gson();

    @Test
    public void sourceKindAcceptsLocalCatalogAndFutureValues() {
        Source local = gson.fromJson("{\"kind\":\"local_catalog\",\"title\":\"本地事项\"}", Source.class);
        Source future = gson.fromJson("{\"kind\":\"future_source\"}", Source.class);

        assertEquals("local_catalog", local.getKind());
        assertEquals("future_source", future.getKind());
    }

    @Test
    public void toolCallAndFailureDetailsAreStrongAndDefensive() {
        ToolCall tool = gson.fromJson("{\"name\":\"search_services\",\"success\":true,"
            + "\"arguments\":{\"query\":\"社保\"},\"result\":{\"count\":1},"
            + "\"duration_ms\":7,\"cached\":true}", ToolCall.class);
        assertEquals("search_services", tool.getName());
        assertTrue(tool.isSuccess());
        assertEquals(7, tool.getDurationMs());
        assertTrue(tool.isCached());
        assertEquals("社保", tool.getArguments().get("query").getAsString());

        JsonObject details = new JsonObject();
        details.addProperty("job_id", "job-1");
        ApiFailure failure = new ApiFailure(409, "index_failed", "失败", details);
        JsonObject copy = failure.getDetails().getAsJsonObject();
        copy.addProperty("access_token", "should-stay-local-to-copy");
        assertEquals("job-1", failure.getDetails().getAsJsonObject().get("job_id").getAsString());
        assertFalse(failure.getDetails().getAsJsonObject().has("access_token"));
    }
}
