(function (root, factory) {
    'use strict';
    const policy = factory();
    if (typeof module === 'object' && module.exports) module.exports = policy;
    if (root) root.MaterialPollPolicy = policy;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    const MAX_TOTAL_MS = 5 * 60 * 1000;
    const TERMINAL = new Set(['READY', 'FAILED', 'EXPIRED']);

    const elapsedMs = (startedAt, now) => {
        const start = Number(startedAt);
        const current = Number(now);
        if (!Number.isFinite(start) || start <= 0 || !Number.isFinite(current)) return 0;
        return Math.max(0, current - start);
    };

    const delayForElapsed = (elapsed) => {
        const value = Math.max(0, Number(elapsed) || 0);
        if (value < 30 * 1000) return 2000;
        if (value < 2 * 60 * 1000) return 5000;
        return 10000;
    };

    const canPoll = ({generationId, status, section, startedAt, now}) => Boolean(generationId)
        && section === 'applications'
        && !TERMINAL.has(String(status || '').toUpperCase())
        && elapsedMs(startedAt, now) < MAX_TOTAL_MS;

    return Object.freeze({MAX_TOTAL_MS, elapsedMs, delayForElapsed, canPoll});
}));
