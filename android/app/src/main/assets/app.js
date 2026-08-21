(() => {
    'use strict';

    const form = document.getElementById('chat-form');
    const message = document.getElementById('message');
    const submit = document.getElementById('submit');
    const map = document.getElementById('map');
    const answer = document.getElementById('answer');
    const metadata = document.getElementById('metadata');
    const nativeStatus = document.getElementById('native-status');

    const setBusy = (busy) => {
        submit.disabled = busy;
        message.disabled = busy;
        submit.textContent = busy ? '处理中…' : '发送问题';
    };

    const showError = (text) => {
        setBusy(false);
        answer.textContent = text || '请求失败，请稍后重试。';
        metadata.hidden = true;
    };

    window.GovAssistant = Object.freeze({
        onNativeReady(status) {
            nativeStatus.textContent = status;
        },
        onNativeResponse(payload) {
            setBusy(false);
            answer.textContent = payload.answer || '后端未返回答复。';
            metadata.textContent = JSON.stringify({
                request_id: payload.request_id,
                session_id: payload.session_id,
                cache_hit: Boolean(payload.cache_hit),
                sources: payload.sources || [],
                tool_calls: payload.tool_calls || [],
                warnings: payload.warnings || []
            }, null, 2);
            metadata.hidden = false;
            message.focus();
        },
        onNativeError(payload) {
            showError(payload && payload.message);
        }
    });

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const text = message.value.trim();
        if (!text) {
            showError('请输入政务问题。');
            return;
        }
        if (!window.GovAssistantNative) {
            showError('Android 服务尚未就绪。');
            return;
        }
        setBusy(true);
        answer.textContent = '正在检索政务服务和知识库…';
        metadata.hidden = true;
        window.GovAssistantNative.sendMessage(text);
    });

    map.addEventListener('click', () => {
        if (window.GovAssistantNative) window.GovAssistantNative.openMap();
    });
})();
