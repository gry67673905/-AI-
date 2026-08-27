'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const asset = (name) => fs.readFileSync(
    path.join(__dirname, '../../main/assets', name), 'utf8'
);

test('consultation renders a transcript, history and a fixed composer', () => {
    const html = asset('index.html');
    assert.match(html, /id="chat-transcript"[^>]*role="log"/);
    assert.match(html, /id="chat-history-panel"/);
    assert.match(html, /id="chat-new"/);
    assert.match(html, /id="chat-form"[^>]*class="chat-composer"/);
    assert.doesNotMatch(html, /id="chat-answer"/);
});

test('chat material cards use opaque ids and the native secure save boundary', () => {
    const source = asset('portal-app-v2.js');
    assert.match(source, /CONSULTATION_MATERIAL_CONFIRM/);
    assert.match(source, /saveGeneratedDocument\(node\.dataset\.generationId\)/);
    assert.match(source, /chatMaterialJobs = new Map\(\)/);
    assert.match(source, /title\.textContent = String\(card\.(?:template_title|title)/);
    assert.match(source, /自动刷新已暂停，可手动继续查询/);
    assert.match(source, /继续查询状态/);
    assert.doesNotMatch(source, /card\.download_url/);
    assert.doesNotMatch(source, /innerHTML\s*=/);
});

test('a failed stream preserves the question and retries with a fresh request', () => {
    const source = asset('portal-app-v2.js');
    assert.match(source, /const renderChatRetry = \(turn\) =>/);
    assert.match(source, /const message = String\(turn\.userBubble\.textContent/);
    assert.match(source, /const requestId = nextRequestId\(\)/);
    assert.match(source, /createChatTurn\(requestId, message\)/);
    assert.match(source, /invoke\('CHAT_STREAM', payload, null, requestId\)/);
    assert.doesNotMatch(source, /invoke\('CHAT_STREAM', payload, null, state\.request_id\)/);
});

test('history and identity transitions cannot reuse an anonymous session', () => {
    const source = asset('portal-app-v2.js');
    assert.match(source, /nextIdentityKey !== lastIdentityKey[\s\S]*chatSessionId = ''/);
    assert.match(source, /kind: 'chat_history_load', sessionId/);
    assert.match(source, /payload\.chat_session_id[\s\S]*CONSULTATION_MESSAGES/);
    assert.match(source, /CHAT_SESSION_RESET/);
});

test('chat transcript and material polling stay bounded', () => {
    const source = asset('portal-app-v2.js');
    assert.match(source, /const MAX_CHAT_TURNS = 50/);
    assert.match(source, /while \(chatTurns\.size > MAX_CHAT_TURNS\)/);
    assert.match(source, /materialPollPolicy\.MAX_TOTAL_MS/);
});
