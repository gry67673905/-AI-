package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;

public final class VisionFrameSelectorTest {
    @Test
    public void continuouslySelectsChangedCandidatesAtTwoFramesPerSecond() {
        VisionFrameSelector selector = new VisionFrameSelector(10.0d);
        byte[] dark = filled(16, 10);
        byte[] bright = filled(16, 80);
        byte[] different = filled(16, 160);

        long turn = selector.beginTurn();
        VisionFrameSelector.Selection start = selector.evaluate(dark, 1_000);
        assertEquals(turn, start.getTurnSeq());
        assertEquals(VisionFrameSelector.Kind.START, start.getKind());
        assertFalse(selector.evaluate(bright, 1_400).isSelected());

        VisionFrameSelector.Selection change = selector.evaluate(bright, 1_500);
        assertEquals(VisionFrameSelector.Kind.CHANGE, change.getKind());
        assertFalse(selector.evaluate(different, 1_900).isSelected());
        assertEquals(
            VisionFrameSelector.Kind.CHANGE,
            selector.evaluate(different, 2_000).getKind()
        );

        selector.requestFinal();
        VisionFrameSelector.Selection end = selector.evaluate(different, 2_100);
        assertEquals(VisionFrameSelector.Kind.FINAL, end.getKind());
        assertEquals(4, end.getIndexInTurn());
        assertEquals(0, selector.getActiveTurnSeq());
    }

    @Test
    public void reservesEighthSlotForFinalAfterSevenNonFinalFrames() {
        VisionFrameSelector selector = new VisionFrameSelector(1.0d);
        long turn = selector.beginTurn();

        for (int index = 0; index < VisionFrameSelector.MAX_NON_FINAL_FRAMES_PER_TURN; index++) {
            VisionFrameSelector.Selection selected = selector.evaluate(
                filled(16, 10 + index * 20),
                1_000L + index * VisionFrameSelector.MIN_CHANGE_INTERVAL_MS
            );
            assertTrue(selected.isSelected());
            assertFalse(selected.isFinal());
        }
        assertFalse(selector.evaluate(filled(16, 240), 5_000).isSelected());

        selector.requestFinal();
        VisionFrameSelector.Selection end = selector.evaluate(filled(16, 240), 5_001);
        assertEquals(turn, end.getTurnSeq());
        assertTrue(end.isFinal());
        assertEquals(VisionFrameSelector.MAX_FRAMES_PER_TURN, end.getIndexInTurn());
    }

    @Test
    public void acceptedPreRollFramesSeedTurnAndCountAgainstNonFinalBudget() {
        VisionFrameSelector selector = new VisionFrameSelector(10.0d);
        selector.beginTurn();

        assertTrue(selector.recordPreRollFrame(filled(16, 20), 1_000));
        assertTrue(selector.recordPreRollFrame(filled(16, 30), 1_500));
        assertFalse(selector.isImmediateFrameRequested());
        assertFalse(selector.evaluate(filled(16, 30), 2_000).isSelected());
        VisionFrameSelector.Selection changed = selector.evaluate(filled(16, 90), 2_000);
        assertEquals(VisionFrameSelector.Kind.CHANGE, changed.getKind());
        assertEquals(3, changed.getIndexInTurn());
    }

    @Test
    public void shortTurnUsesOnePhysicallyFinalFrame() {
        VisionFrameSelector selector = new VisionFrameSelector();
        long turn = selector.requestFinal();

        VisionFrameSelector.Selection selected = selector.evaluate(filled(16, 40), 5_000);

        assertTrue(selected.isFinal());
        assertEquals(turn, selected.getTurnSeq());
        assertEquals(1, selected.getIndexInTurn());
    }

    @Test
    public void timeoutCompletesOnlyMatchingTurn() {
        VisionFrameSelector selector = new VisionFrameSelector();
        long turn = selector.requestFinal();

        assertFalse(selector.completeWithoutFrame(turn + 1));
        assertTrue(selector.completeWithoutFrame(turn));
        assertFalse(selector.isImmediateFrameRequested());
    }

    private static byte[] filled(int size, int value) {
        byte[] result = new byte[size];
        Arrays.fill(result, (byte) value);
        return result;
    }
}
