package com.example.aicompanion.metastudio.vision;

import java.util.Arrays;

/**
 * Continuously evaluates sparse camera candidates during one ASR turn.
 *
 * <p>At most seven non-final frames may be selected or restored from the short pre-roll
 * buffer. The eighth slot is reserved for the physically final frame.</p>
 */
public final class VisionFrameSelector {
    public static final int MAX_FRAMES_PER_TURN = 8;
    public static final int MAX_NON_FINAL_FRAMES_PER_TURN = MAX_FRAMES_PER_TURN - 1;
    public static final long MIN_CHANGE_INTERVAL_MS = 500L;
    public static final double DEFAULT_CHANGE_THRESHOLD = 18.0d;

    private final double changeThreshold;
    private long nextTurnSeq;
    private long activeTurnSeq;
    private long lastSelectedAtMs;
    private int frameCount;
    private boolean forceStart;
    private boolean finalRequested;
    private byte[] lastSelectedSignature;

    public VisionFrameSelector() {
        this(DEFAULT_CHANGE_THRESHOLD);
    }

    VisionFrameSelector(double changeThreshold) {
        if (changeThreshold < 0 || changeThreshold > 255) {
            throw new IllegalArgumentException("Invalid scene-change threshold");
        }
        this.changeThreshold = changeThreshold;
    }

    public synchronized long beginTurn() {
        if (activeTurnSeq > 0) return activeTurnSeq;
        nextTurnSeq = nextTurnSeq == Long.MAX_VALUE ? 1 : nextTurnSeq + 1;
        activeTurnSeq = nextTurnSeq;
        lastSelectedAtMs = 0;
        frameCount = 0;
        forceStart = true;
        finalRequested = false;
        lastSelectedSignature = null;
        return activeTurnSeq;
    }

    /** Count one already encoded pre-roll image that the transport accepted for this turn. */
    public synchronized boolean recordPreRollFrame(byte[] signature, long capturedAtMs) {
        if (activeTurnSeq < 1 || finalRequested || signature == null || signature.length < 8
            || capturedAtMs < 1 || frameCount >= MAX_NON_FINAL_FRAMES_PER_TURN) {
            return false;
        }
        frameCount++;
        forceStart = false;
        lastSelectedAtMs = capturedAtMs;
        lastSelectedSignature = Arrays.copyOf(signature, signature.length);
        return true;
    }

    public synchronized long requestFinal() {
        long turnSeq = activeTurnSeq > 0 ? activeTurnSeq : beginTurn();
        finalRequested = true;
        return turnSeq;
    }

    public synchronized Selection evaluate(byte[] signature, long capturedAtMs) {
        if (activeTurnSeq < 1 || signature == null || signature.length < 8 || capturedAtMs < 1) {
            return Selection.none();
        }
        Kind kind = Kind.NONE;
        if (finalRequested) {
            kind = Kind.FINAL;
        } else if (forceStart && frameCount < MAX_NON_FINAL_FRAMES_PER_TURN) {
            kind = Kind.START;
        } else if (frameCount < MAX_NON_FINAL_FRAMES_PER_TURN
            && capturedAtMs - lastSelectedAtMs >= MIN_CHANGE_INTERVAL_MS
            && meanAbsoluteDifference(lastSelectedSignature, signature) >= changeThreshold) {
            kind = Kind.CHANGE;
        }
        if (kind == Kind.NONE) return Selection.none();

        frameCount++;
        forceStart = false;
        lastSelectedAtMs = capturedAtMs;
        lastSelectedSignature = Arrays.copyOf(signature, signature.length);
        long selectedTurn = activeTurnSeq;
        int selectedIndex = frameCount;
        if (kind == Kind.FINAL) clearActiveTurn();
        return new Selection(kind, selectedTurn, selectedIndex);
    }

    public synchronized long getActiveTurnSeq() { return activeTurnSeq; }

    public synchronized boolean isImmediateFrameRequested() {
        return activeTurnSeq > 0 && (forceStart || finalRequested);
    }

    public synchronized boolean completeWithoutFrame(long turnSeq) {
        if (turnSeq < 1 || activeTurnSeq != turnSeq) return false;
        clearActiveTurn();
        return true;
    }

    public synchronized void reset() {
        clearActiveTurn();
    }

    private void clearActiveTurn() {
        activeTurnSeq = 0;
        lastSelectedAtMs = 0;
        frameCount = 0;
        forceStart = false;
        finalRequested = false;
        lastSelectedSignature = null;
    }

    static double meanAbsoluteDifference(byte[] left, byte[] right) {
        if (left == null || right == null || left.length != right.length || left.length == 0) {
            return 255.0d;
        }
        long sum = 0;
        for (int index = 0; index < left.length; index++) {
            sum += Math.abs((left[index] & 0xff) - (right[index] & 0xff));
        }
        return (double) sum / left.length;
    }

    public enum Kind { NONE, START, CHANGE, FINAL }

    public static final class Selection {
        private static final Selection NONE = new Selection(Kind.NONE, 0, 0);
        private final Kind kind;
        private final long turnSeq;
        private final int indexInTurn;

        private Selection(Kind kind, long turnSeq, int indexInTurn) {
            this.kind = kind;
            this.turnSeq = turnSeq;
            this.indexInTurn = indexInTurn;
        }

        static Selection none() { return NONE; }
        public boolean isSelected() { return kind != Kind.NONE; }
        public boolean isFinal() { return kind == Kind.FINAL; }
        public Kind getKind() { return kind; }
        public long getTurnSeq() { return turnSeq; }
        public int getIndexInTurn() { return indexInTurn; }
    }
}
