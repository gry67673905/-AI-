'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const messages = [];
const nativeListeners = {};
const windowListeners = {};
let launch;

const element = () => ({
    hidden: true,
    textContent: '',
    addEventListener: () => {}
});

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

    const statuses = messages.filter((message) => message.event === 'sdk_status')
        .map((message) => message.status);
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
})().catch((error) => {
    process.stderr.write(`${error.name}: diagnostic wrapper test failed\n`);
    process.exitCode = 1;
});
