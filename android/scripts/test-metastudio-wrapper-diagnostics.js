'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const messages = [];
const nativeListeners = {};
const windowListeners = {};
let launch;

const elements = new Map();
const element = (id) => {
    if (elements.has(id)) return elements.get(id);
    const value = {
        hidden: true,
        textContent: '',
        dataset: {},
        attributes: {},
        addEventListener: () => {},
        setAttribute(name, content) { this.attributes[name] = String(content); }
    };
    elements.set(id, value);
    return value;
};

const windowStub = {
    GovDigitalHumanNative: {
        postMessage: (raw) => messages.push(JSON.parse(raw)),
        addEventListener: (name, listener) => { nativeListeners[name] = listener; }
    },
    HwICSUiSdk: {
        checkBrowserSupport: async () => true,
        create: async (value) => { launch = value; },
        destroy: async () => {}
    },
    addEventListener: (name, listener) => { windowListeners[name] = listener; }
};

const context = {
    window: windowStub,
    document: {getElementById: element},
    URL,
    JSON,
    Object,
    Array,
    Number,
    String,
    Promise
};

const source = fs.readFileSync(
    path.join(__dirname, '..', 'app', 'src', 'main', 'assets', 'metastudio', 'app.js'),
    'utf8'
);
const portalSource = fs.readFileSync(
    path.join(__dirname, '..', 'app', 'src', 'main', 'assets', 'portal-app-v2.js'),
    'utf8'
);
const portalHtml = fs.readFileSync(
    path.join(__dirname, '..', 'app', 'src', 'main', 'assets', 'index.html'),
    'utf8'
);
const portalStyle = fs.readFileSync(
    path.join(__dirname, '..', 'app', 'src', 'main', 'assets', 'style.css'),
    'utf8'
);
const metastudioHtml = fs.readFileSync(
    path.join(__dirname, '..', 'app', 'src', 'main', 'assets', 'metastudio', 'index.html'),
    'utf8'
);
assert(metastudioHtml.includes('<script defer src="app.js"></script>'),
    'MetaStudio wrapper must use the exact trusted local asset URL');
assert(portalSource.includes('openServiceNavigation'), 'portal service navigation entry missing');
assert(portalHtml.includes('digital-human-navigation-confirmation'), 'navigation confirmation card missing');
assert(portalHtml.includes('id="login-show-register"'), 'visible registration shortcut missing');
assert(portalSource.includes("bindClick('login-show-register'"), 'registration shortcut handler missing');
assert(portalSource.includes("case 'AUTH_SEND_CODE':"), 'registration code autofill is missing');
assert(portalSource.includes("byId('register-code').value = data.demo_code"), 'demo code must be visible at the form');
assert(portalSource.includes("querySelectorAll('.workspace[data-section]')"), 'section switching must not hide navigation buttons');
assert(!portalSource.includes("querySelectorAll('[data-section]')"), 'broad section selector hides navigation buttons');
assert(portalStyle.includes('grid-template-columns: repeat(3, minmax(0, 1fr))'), 'mobile navigation must expose every entry');
assert(portalHtml.includes('style.css?v=portal-20260827-contextual-chat-1'), 'portal stylesheet cache buster missing');
assert(portalHtml.includes('portal-app-v2.js?v=portal-20260827-contextual-chat-1'), 'portal script cache buster missing');
for (const forbiddenPortalEntry of ['openWindowMap', 'window-map-form', 'id="window-id"']) {
    assert(!portalSource.includes(forbiddenPortalEntry), `portal JS retained ${forbiddenPortalEntry}`);
    assert(!portalHtml.includes(forbiddenPortalEntry), `portal HTML retained ${forbiddenPortalEntry}`);
}
vm.runInNewContext(source, context, {filename: 'app.js'});

const settle = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
    await settle();
    nativeListeners.message({data: JSON.stringify({
        type: 'client_session',
        session_id: 'session-test',
        server_address: 'metastudio-api.cn-north-4.myhuaweicloud.com',
        robot_id: 'robot-test',
        once_code: 'ONCE-CODE-MUST-NOT-LEAK'
    })});
    await settle();
    assert(launch && launch.eventListeners);
    assert.strictEqual(launch.config.enableCollectAudioDemand, false);
    assert.strictEqual(launch.config.enableVadInterrupt, true);
    assert.strictEqual(launch.config.enableCaption, true);
    assert.strictEqual(launch.config.enableChatBtn, true);

    const firstPartial = '我想办';
    const revisedPartial = '我想办理公积金';
    const finalText = '我想办理公积金提取。';
    const statusValues = () => messages.filter((message) => message.event === 'sdk_status')
        .map((message) => message.status);
    let messageCount = messages.length;

    // Malformed ASR and semantic events cannot bootstrap a conversation.
    launch.eventListeners.speechRecognized({
        chatId: '<invalid>', resultId: 1, isLast: false, text: '无效激活语音'
    });
    launch.eventListeners.semanticRecognized({
        chatId: 'semantic-before-active', isLast: true,
        extendParam: {intent_id: 'intent-before-active', requires_confirmation: true}
    });
    assert.strictEqual(messages.length, messageCount);

    // A schema-valid speech packet is authoritative even when a provider/WebView
    // re-entry race omits enterActive. This keeps ASR-driven vision turns alive.
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-1', resultId: 1, isLast: false, text: firstPartial
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.strictEqual(statusValues().at(-1), 'asr_partial');
    assert.strictEqual(element('local-caption').hidden, false);
    assert.strictEqual(element('local-caption-text').textContent, firstPartial);
    assert.strictEqual(element('local-caption').attributes['data-final'], 'false');
    messageCount = messages.length;

    // MetaStudio's own caption UI performs overwrite rendering. The wrapper
    // validates revisions but does not forward repeated partial packets.
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-1', resultId: 2, isLast: false, text: revisedPartial
    });
    assert.strictEqual(messages.length, messageCount);
    assert.strictEqual(element('local-caption-text').textContent, revisedPartial);
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-1', resultId: 1, isLast: false, text: '旧结果'
    });
    assert.strictEqual(element('local-caption-text').textContent, revisedPartial);
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-1', resultId: 3, isLast: 'true', text: '字符串真值'
    });
    assert.strictEqual(messages.length, messageCount);

    launch.eventListeners.speechRecognized({
        // The SDK does not promise monotonic result IDs; a valid terminal
        // packet must still close the active turn when its ID is lower.
        chatId: 'chat-stream-1', resultId: 0, isLast: true, text: finalText
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.strictEqual(statusValues().at(-1), 'asr_final');
    assert.strictEqual(element('local-caption-text').textContent, finalText);
    assert.strictEqual(element('local-caption').attributes['data-final'], 'true');
    messageCount = messages.length;

    // Once final, a duplicated terminal packet or later partial packet for the same chat cannot
    // emit a second native turn-end state (and therefore cannot close/upload/model-call twice).
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-1', resultId: 3, isLast: true, text: finalText
    });
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-1', resultId: 4, isLast: false, text: '最终包后的旧流'
    });
    assert.strictEqual(messages.length, messageCount);

    launch.eventListeners.speakingStart();
    assert.strictEqual(messages.length, messageCount + 1);
    assert.strictEqual(statusValues().at(-1), 'answering');
    messageCount = messages.length;

    // A new chat starts one fixed partial state. Late packets from the retired
    // chat, invalid fields, and oversized text never cross the bridge.
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-2', resultId: 1, isLast: false, text: '下一轮继续提问'
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.strictEqual(statusValues().at(-1), 'asr_partial');
    messageCount = messages.length;

    // A delayed speakingStop from the interrupted answer must not overwrite
    // the already-started ASR state for this new voice turn.
    launch.eventListeners.speakingStop();
    assert.strictEqual(messages.length, messageCount);
    assert.strictEqual(statusValues().at(-1), 'asr_partial');

    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-1', resultId: 99, isLast: true, text: '迟到的上一轮'
    });
    launch.eventListeners.speechRecognized({
        chatId: '<script>', resultId: 2, isLast: false, text: '不可信标识'
    });
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-2', resultId: 2, isLast: false, text: 'x'.repeat(4097)
    });
    launch.eventListeners.speechRecognized({
        chatId: 'chat-stream-2', resultId: 2, isLast: false, text: {value: '对象文本'}
    });
    for (const invalidQuestion of [
        {chatId: 7, resultId: 2, isLast: false, text: '数字标识'},
        {chatId: 'chat-stream-2', resultId: -1, isLast: false, text: '负数'},
        {chatId: 'chat-stream-2', resultId: 1.5, isLast: false, text: '小数'},
        {chatId: 'chat-stream-2', resultId: NaN, isLast: false, text: '非数字'},
        {chatId: 'chat-stream-2', resultId: Infinity, isLast: false, text: '无穷'},
        {chatId: 'chat-stream-2', resultId: Number.MAX_SAFE_INTEGER + 1, isLast: false, text: '非安全整数'},
        {chatId: 'chat-stream-2', resultId: 2, text: '缺少最终标记'}
    ]) {
        launch.eventListeners.speechRecognized(invalidQuestion);
    }
    assert.strictEqual(messages.length, messageCount);

    const boundaryText = '界'.repeat(4096);
    launch.eventListeners.speechRecognized({
        chatId: 'chat-boundary', resultId: Number.MAX_SAFE_INTEGER, isLast: false, text: boundaryText
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.strictEqual(statusValues().at(-1), 'asr_partial');
    launch.eventListeners.speechRecognized({
        chatId: 'chat-boundary', resultId: 0, isLast: true, text: boundaryText
    });
    assert.strictEqual(statusValues().at(-1), 'asr_final');

    launch.eventListeners.speakingStart();
    assert.strictEqual(statusValues().at(-1), 'answering');
    launch.eventListeners.speakingStop();
    assert.strictEqual(statusValues().at(-1), 'active');

    // Five uninterrupted VAD-delimited rounds remain inside one explicitly started chat. Each
    // round exports exactly one partial state and one final state; caption text stays in the
    // isolated wrapper DOM and never crosses the native bridge.
    const fiveRoundPrivate = [];
    for (let round = 1; round <= 5; round += 1) {
        const partial = `连续轮次${round}中间字幕`;
        const revised = `连续轮次${round}修订字幕`;
        const final = `连续轮次${round}最终问题`;
        const chatId = `continuous-chat-${round}`;
        fiveRoundPrivate.push(partial, revised, final, chatId);
        messageCount = messages.length;
        launch.eventListeners.speechRecognized({chatId, resultId: 1, isLast: false, text: partial});
        assert.strictEqual(messages.length, messageCount + 1);
        assert.strictEqual(statusValues().at(-1), 'asr_partial');
        launch.eventListeners.speechRecognized({chatId, resultId: 2, isLast: false, text: revised});
        assert.strictEqual(messages.length, messageCount + 1);
        assert.strictEqual(element('local-caption-text').textContent, revised);
        launch.eventListeners.speechRecognized({chatId, resultId: 3, isLast: true, text: final});
        assert.strictEqual(messages.length, messageCount + 2);
        assert.strictEqual(statusValues().at(-1), 'asr_final');
        assert.strictEqual(element('local-caption-text').textContent, final);
        launch.eventListeners.speechRecognized({chatId, resultId: 4, isLast: true, text: final});
        assert.strictEqual(messages.length, messageCount + 2);
        launch.eventListeners.speakingStart();
        launch.eventListeners.speakingStop();
        assert.strictEqual(statusValues().at(-1), 'active');
    }
    const continuousSerialized = JSON.stringify(messages);
    for (const privateTranscript of fiveRoundPrivate) {
        assert(!continuousSerialized.includes(privateTranscript),
            'continuous ASR caption crossed the native bridge');
    }

    messageCount = messages.length;
    const semanticPrivate = '模型回答原文不得跨桥';
    launch.eventListeners.semanticRecognized({
        chatId: 123, isLast: true, text: semanticPrivate,
        extendParam: {intent_id: 'intent-safe', requires_confirmation: true}
    });
    launch.eventListeners.semanticRecognized({
        chatId: 'semantic-chat', isLast: true, text: semanticPrivate,
        extendParam: 'x'.repeat(4097)
    });
    assert.strictEqual(messages.length, messageCount);
    launch.eventListeners.semanticRecognized({
        chatId: 'semantic-chat', isLast: true, text: semanticPrivate,
        extendParam: {intent_id: 'intent-safe', requires_confirmation: true}
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.deepStrictEqual(messages.at(-1), {
        event: 'semantic_final', chat_id: 'semantic-chat',
        intent_id: 'intent-safe', is_last: true
    });

    const semanticQuestionPrivate = '用户问题原文不得跨桥';
    const extensionPrivate = '扩展字段中的多余文字不得跨桥';
    messageCount = messages.length;
    launch.eventListeners.semanticRecognized({
        chatId: 'semantic-json', isLast: true, text: semanticPrivate,
        questionText: semanticQuestionPrivate,
        extendParam: JSON.stringify({
            intent_id: 'intent-json', requires_confirmation: true, text: extensionPrivate
        })
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.deepStrictEqual(messages.at(-1), {
        event: 'semantic_final', chat_id: 'semantic-json',
        intent_id: 'intent-json', is_last: true
    });

    launch.eventListeners.jobInfoChange({
        isReady: true,
        jobId: 'job-test',
        websocketAddr: 'metastudio-client.cn-north-4.myhuaweicloud.com:6447/ws?token=HOST-TOKEN'
    });
    windowListeners.securitypolicyviolation({
        effectiveDirective: 'connect-src',
        blockedURI: 'wss://metastudio-client.cn-north-4.myhuaweicloud.com/private?token=CSP-TOKEN'
    });
    windowListeners.securitypolicyviolation({
        effectiveDirective: 'connect-src',
        blockedURI: 'wss://rtc-node.dbankcdn.com:6447/private?token=RTC-TOKEN'
    });
    windowListeners.securitypolicyviolation({
        effectiveDirective: 'connect-src',
        blockedURI: 'https://unlisted.example:7443/private?token=OTHER-TOKEN'
    });

    const statuses = statusValues();
    assert(statuses.includes('ready_ws_client_6447'));
    assert(statuses.includes('csp_connect_client_443'));
    assert(statuses.includes('csp_connect_rtc_6447'));
    assert(statuses.includes('csp_connect_other_other'));

    const serialized = JSON.stringify(messages);
    for (const forbidden of [
        'metastudio-client', 'dbankcdn', 'unlisted.example', '/private',
        'HOST-TOKEN', 'CSP-TOKEN', 'RTC-TOKEN', 'OTHER-TOKEN', 'ONCE-CODE-MUST-NOT-LEAK'
    ]) {
        assert(!serialized.includes(forbidden), `diagnostic message leaked ${forbidden}`);
    }
    for (const privateTranscript of [
        firstPartial, revisedPartial, finalText, '下一轮继续提问',
        'chat-stream-1', 'chat-stream-2', '迟到的上一轮', semanticPrivate,
        semanticQuestionPrivate, extensionPrivate
    ]) {
        assert(!serialized.includes(privateTranscript), 'ASR transcript crossed the native bridge');
    }

    launch.eventListeners.enterSleep();
    assert.strictEqual(statusValues().at(-1), 'ready');
    assert.strictEqual(element('local-caption').hidden, true);
    assert.strictEqual(element('local-caption-text').textContent, '');
    messageCount = messages.length;
    // Semantic data alone cannot reactivate the wrapper.
    launch.eventListeners.semanticRecognized({
        chatId: 'semantic-after-sleep', isLast: true,
        extendParam: {intent_id: 'intent-after-sleep', requires_confirmation: true}
    });
    assert.strictEqual(messages.length, messageCount);

    // The provider may again omit enterActive after waking/re-entry. A valid
    // ASR packet must still start the native vision turn exactly once.
    launch.eventListeners.speechRecognized({
        chatId: 'chat-after-sleep', resultId: 1, isLast: false, text: '休眠后新一轮'
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.strictEqual(statusValues().at(-1), 'asr_partial');
    messageCount = messages.length;
    launch.eventListeners.enterActive();
    assert.strictEqual(messages.length, messageCount);
    launch.eventListeners.speechRecognized({
        chatId: 'chat-after-sleep', resultId: 2, isLast: true, text: '再次激活后新一轮'
    });
    assert.strictEqual(messages.length, messageCount + 1);
    assert.strictEqual(statusValues().at(-1), 'asr_final');

    launch.eventListeners.jobEnd();
    assert.strictEqual(statusValues().at(-1), 'ended');
    messageCount = messages.length;
    launch.eventListeners.speechRecognized({
        chatId: 'chat-after-end', resultId: 1, isLast: true, text: '结束后的迟到语音'
    });
    launch.eventListeners.semanticRecognized({
        chatId: 'semantic-after-end', isLast: true,
        extendParam: {intent_id: 'intent-after-end', requires_confirmation: true}
    });
    launch.eventListeners.enterActive();
    launch.eventListeners.speakingStart();
    launch.eventListeners.speakingStop();
    assert.strictEqual(messages.length, messageCount);
    assert.strictEqual(statusValues().at(-1), 'ended');

    const lifecycleSerialized = JSON.stringify(messages);
    for (const privateAfterLifecycle of [
        '激活前的迟到语音', '休眠后新一轮', '再次激活后新一轮',
        '结束后的迟到语音', 'chat-after-reactivate', 'chat-after-end'
    ]) {
        assert(!lifecycleSerialized.includes(privateAfterLifecycle), 'lifecycle event leaked ASR data');
    }
    windowListeners.pagehide();
})().catch((error) => {
    process.stderr.write(`${error.name}: diagnostic wrapper test failed\n`);
    process.exitCode = 1;
});
