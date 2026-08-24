package com.example.aicompanion.metastudio.business;

import java.util.LinkedHashMap;
import java.util.Map;

/** Bounded LRU de-duplication for repeated final streaming packets. */
public final class SemanticIntentDeduplicator {
    private static final int MAX_KEYS = 256;
    private final Map<String, Boolean> seen = new LinkedHashMap<String, Boolean>(MAX_KEYS, 0.75f, true) {
        @Override protected boolean removeEldestEntry(Map.Entry<String, Boolean> eldest) {
            return size() > MAX_KEYS;
        }
    };

    public synchronized boolean accept(String chatId, String intentId) {
        String key = (chatId == null ? "" : chatId) + "\n" + (intentId == null ? "" : intentId);
        if (seen.containsKey(key)) return false;
        seen.put(key, Boolean.TRUE);
        return true;
    }

    public synchronized int size() { return seen.size(); }
}
