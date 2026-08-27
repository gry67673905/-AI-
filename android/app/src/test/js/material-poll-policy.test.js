'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const policy = require('../../main/assets/material-poll-policy.js');

test('polling has a five minute wall-clock bound', () => {
    const startedAt = 1000;
    const base = {
        generationId: 'generation-1',
        status: 'RUNNING',
        section: 'applications',
        startedAt
    };
    assert.equal(policy.canPoll({...base, now: startedAt + policy.MAX_TOTAL_MS - 1}), true);
    assert.equal(policy.canPoll({...base, now: startedAt + policy.MAX_TOTAL_MS}), false);
    assert.equal(policy.canPoll({...base, status: 'READY', now: startedAt + 1000}), false);
    assert.equal(policy.canPoll({...base, section: 'services', now: startedAt + 1000}), false);
});

test('poll interval backs off from two to five to ten seconds', () => {
    assert.equal(policy.delayForElapsed(0), 2000);
    assert.equal(policy.delayForElapsed(30_000), 5000);
    assert.equal(policy.delayForElapsed(120_000), 10_000);
});

test('portal exposes manual retry and clears stale template selection', () => {
    const source = fs.readFileSync(
        path.join(__dirname, '../../main/assets/portal-app-v2.js'), 'utf8'
    );
    assert.match(source, /bindClick\('material-generation-refresh'[\s\S]*resetMaterialPollWindow\(\)/);
    assert.match(source, /application-id'\)\.addEventListener\('input'[\s\S]*clearMaterialTemplateSelection\(true\)/);
    assert.match(source, /material-template-load'[\s\S]*clearMaterialTemplateSelection\(true\)/);
});
