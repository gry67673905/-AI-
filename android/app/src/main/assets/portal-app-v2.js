(() => {
    'use strict';

    const byId = (id) => document.getElementById(id);
    const bridge = () => window.GovPortalNative;
    const materialPollPolicy = window.MaterialPollPolicy;
    if (!materialPollPolicy) throw new Error('材料生成轮询策略未加载');
    const activityOutput = byId('activity-output');
    const alertBox = byId('global-alert');
    let requestCounter = 0;
    let role = 'ANONYMOUS';
    let user = {role: 'ANONYMOUS', display_name: '访客', applicant_type: 'NONE'};
    let currentSection = 'consultation';
    let pendingNavigationServiceId = '';
    let nativeBusy = false;
    let materialGenerationId = '';
    let materialGenerationStatus = '';
    let materialPollTimer = null;
    let materialPollStartedAt = 0;
    let materialPollPaused = false;
    let chatSessionId = '';
    let pendingHistoryRestoreSessionId = '';
    let lastIdentityKey = '';
    const chatTurns = new Map();
    const pendingRequests = new Map();
    const chatMaterialJobs = new Map();
    const MAX_CHAT_TURNS = 50;
    const canonicalUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

    const navigation = Object.freeze({
        ANONYMOUS: [['consultation', 'AI 咨询'], ['services', '事项服务'], ['login', '登录 / 注册']],
        CITIZEN: [['consultation', 'AI 咨询'], ['services', '事项服务'], ['applications', '我的办件'], ['profile', '账号']],
        STAFF: [['staff_tasks', '审核待办'], ['staff_handoffs', '人工咨询'], ['profile', '账号']],
        ADMIN: [['admin_overview', '运营概览'], ['admin_catalog', '事项管理'], ['admin_people', '人员管理'], ['admin_knowledge', '知识资料'], ['admin_audit', '审计'], ['profile', '账号']]
    });

    const nextRequestId = () => `android-${Date.now()}-${++requestCounter}`;

    const showAlert = (message, kind = 'error') => {
        alertBox.textContent = message || '操作失败，请稍后重试。';
        alertBox.dataset.kind = kind;
        alertBox.hidden = false;
    };

    const clearAlert = () => {
        alertBox.hidden = true;
        alertBox.textContent = '';
    };

    const setBusy = (busy) => {
        nativeBusy = Boolean(busy);
        document.querySelectorAll('[data-native-action]').forEach((element) => {
            element.disabled = Boolean(busy);
        });
        document.body.dataset.busy = busy ? 'true' : 'false';
    };

    const safeJson = (raw, fallback = {}) => {
        try {
            const parsed = JSON.parse(String(raw || '').trim() || '{}');
            if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('必须是 JSON 对象');
            return parsed;
        } catch (error) {
            showAlert(`JSON 格式错误：${error.message}`);
            return fallback;
        }
    };

    const requiredValue = (id, label) => {
        const value = byId(id).value.trim();
        if (!value) throw new Error(`请输入${label}`);
        return value;
    };

    const invoke = (command, payload = {}, context = null, fixedRequestId = '') => {
        clearAlert();
        const nativeBridge = bridge();
        if (!nativeBridge || typeof nativeBridge.execute !== 'function') {
            showAlert('Android 原生服务尚未就绪。');
            return '';
        }
        const requestId = fixedRequestId || nextRequestId();
        if (context) pendingRequests.set(requestId, context);
        nativeBridge.execute(JSON.stringify({request_id: requestId, command, payload}));
        return requestId;
    };

    const guarded = (callback) => (event) => {
        if (event) event.preventDefault();
        try { callback(); } catch (error) { showAlert(error.message); }
    };

    const bindClick = (id, callback) => byId(id).addEventListener('click', guarded(callback));
    const bindSubmit = (id, callback) => byId(id).addEventListener('submit', guarded(callback));

    const selectSection = (section) => {
        const allowed = (navigation[role] || navigation.ANONYMOUS).some(([id]) => id === section);
        currentSection = allowed ? section : (navigation[role] || navigation.ANONYMOUS)[0][0];
        document.querySelectorAll('.workspace[data-section]').forEach((element) => {
            element.hidden = element.dataset.section !== currentSection;
        });
        document.querySelectorAll('#primary-nav button').forEach((button) => {
            button.setAttribute('aria-current', button.dataset.section === currentSection ? 'page' : 'false');
        });
        if (currentSection === 'applications' && materialGenerationId && !materialPollPaused
            && !['READY', 'FAILED', 'EXPIRED'].includes(materialGenerationStatus)) {
            scheduleMaterialPoll(300);
        } else if (currentSection !== 'applications') {
            stopMaterialPoll();
        }
    };

    const applyDigitalHumanIntent = (event) => {
        if (!event.requires_confirmation || typeof event.section !== 'string') {
            showAlert('数字人操作建议未通过确认策略。');
            return;
        }
        if (event.intent_type === 'OPEN_SERVICE_NAVIGATION') {
            const prefill = event.prefill && typeof event.prefill === 'object' && !Array.isArray(event.prefill)
                ? event.prefill : null;
            const keys = prefill ? Object.keys(prefill) : [];
            const serviceId = prefill && typeof prefill.service_id === 'string'
                ? prefill.service_id : '';
            if (event.section !== 'services' || keys.length !== 1 || keys[0] !== 'service_id'
                || !canonicalUuid.test(serviceId)) {
                showAlert('数字人服务导航建议格式无效。');
                return;
            }
            pendingNavigationServiceId = serviceId;
            byId('digital-human-navigation-label').textContent = `数字人建议：${event.label || '查看事项服务网点'}。`;
            byId('digital-human-navigation-confirmation').hidden = false;
            return;
        }
        const allowed = (navigation[role] || navigation.ANONYMOUS).some(([id]) => id === event.section);
        if (!allowed) {
            showAlert('当前账号不能打开数字人建议的工作台。');
            return;
        }
        selectSection(event.section);
        const prefill = event.prefill && typeof event.prefill === 'object' && !Array.isArray(event.prefill)
            ? event.prefill : {};
        const fields = Object.freeze({
            chat_message: ['chat-message'],
            service_query: ['service-query'],
            service_id: ['service-id', 'service-navigation-id', 'application-service-id', 'appointment-service', 'admin-service-id'],
            applicant_type: ['service-applicant'],
            account: ['login-account'],
            application_id: ['application-id', 'payment-application', 'verification-application'],
            requirement_id: ['requirement-id'],
            application_version: ['application-version'],
            payment_id: ['payment-id'],
            verification_id: ['verification-id'],
            delivery_id: ['delivery-id'],
            window_id: ['appointment-window', 'admin-window-id'],
            appointment_id: ['appointment-id'],
            task_id: ['staff-task-id'],
            ticket_id: ['citizen-ticket-id', 'staff-ticket-id'],
            department_id: ['admin-service-department', 'admin-staff-department'],
            user_id: ['admin-user-id'],
            version_id: ['admin-version-id'],
            knowledge_job_id: ['admin-knowledge-job']
        });
        Object.entries(prefill).forEach(([key, value]) => {
            const ids = fields[key];
            if (!ids || typeof value !== 'string') return;
            ids.forEach((id) => {
                const input = byId(id);
                if (input && 'value' in input) input.value = value;
            });
        });
        showAlert(`数字人建议：${event.label || '继续办理'}。请核对预填信息后在当前页面确认。`, 'info');
    };

    const renderNavigation = () => {
        const nav = byId('primary-nav');
        nav.replaceChildren();
        (navigation[role] || navigation.ANONYMOUS).forEach(([section, label]) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'nav-button';
            button.dataset.section = section;
            button.textContent = label;
            button.addEventListener('click', () => selectSection(section));
            nav.appendChild(button);
        });
        document.querySelectorAll('.citizen-only:not([data-section])').forEach((element) => { element.hidden = role !== 'CITIZEN'; });
        document.querySelectorAll('.authenticated-only:not([data-section])').forEach((element) => { element.hidden = role === 'ANONYMOUS'; });
        selectSection(currentSection);
    };

    const normalizeUser = (raw) => {
        const source = raw && typeof raw === 'object' ? raw : {};
        return {
            id: source.id || '',
            display_name: source.display_name || source.displayName || source.name || '访客',
            role: String(source.role || 'ANONYMOUS').toUpperCase(),
            applicant_type: String(source.applicant_type || source.applicantType || 'NONE').toUpperCase()
        };
    };

    const stopChatMaterialJobs = () => {
        chatMaterialJobs.forEach((job) => {
            if (job.timer !== null) window.clearTimeout(job.timer);
        });
        chatMaterialJobs.clear();
    };

    const clearChatTranscript = (message = '可以连续追问，也可以问我“有没有材料模板”。') => {
        stopChatMaterialJobs();
        chatTurns.clear();
        const transcript = byId('chat-transcript');
        transcript.replaceChildren();
        const empty = document.createElement('li');
        empty.id = 'chat-empty';
        empty.className = 'chat-empty';
        empty.textContent = message;
        transcript.appendChild(empty);
    };

    const removeChatEmpty = () => {
        const empty = byId('chat-empty');
        if (empty) empty.remove();
    };

    const scrollChatToEnd = () => {
        const transcript = byId('chat-transcript');
        window.requestAnimationFrame(() => { transcript.scrollTop = transcript.scrollHeight; });
    };

    const trimChatTurns = () => {
        while (chatTurns.size > MAX_CHAT_TURNS) {
            const oldest = chatTurns.entries().next().value;
            if (!oldest) return;
            const [requestId, state] = oldest;
            chatMaterialJobs.forEach((job, generationId) => {
                if (state.turn.contains(job.node)) {
                    if (job.timer !== null) window.clearTimeout(job.timer);
                    chatMaterialJobs.delete(generationId);
                }
            });
            state.turn.remove();
            chatTurns.delete(requestId);
        }
    };

    const createChatTurn = (requestId, userText, assistantText = '') => {
        removeChatEmpty();
        const turn = document.createElement('li');
        turn.className = 'chat-turn';
        turn.dataset.requestId = requestId;
        const userBubble = document.createElement('div');
        userBubble.className = 'chat-bubble chat-bubble-user';
        userBubble.textContent = userText || '';
        userBubble.hidden = !userBubble.textContent;
        const assistantBubble = document.createElement('div');
        assistantBubble.className = 'chat-bubble chat-bubble-assistant';
        assistantBubble.dataset.state = assistantText ? 'done' : 'streaming';
        assistantBubble.textContent = assistantText || '正在思考…';
        const cards = document.createElement('div');
        cards.className = 'chat-turn-cards';
        const actions = document.createElement('div');
        actions.className = 'button-row wrap chat-turn-actions';
        const meta = document.createElement('details');
        meta.className = 'chat-meta';
        meta.hidden = true;
        const summary = document.createElement('summary');
        summary.textContent = '来源与提示';
        const output = document.createElement('pre');
        output.textContent = '暂无';
        meta.append(summary, output);
        turn.append(userBubble, assistantBubble, cards, actions, meta);
        byId('chat-transcript').appendChild(turn);
        const state = {turn, userBubble, assistantBubble, cards, actions, meta, metaOutput: output, answer: ''};
        chatTurns.set(requestId, state);
        trimChatTurns();
        scrollChatToEnd();
        return state;
    };

    const ensureChatTurn = (requestId, userText = '') => {
        const safeId = String(requestId || nextRequestId());
        return chatTurns.get(safeId) || createChatTurn(safeId, userText || byId('chat-message').value.trim());
    };

    const normalizeUiCards = (raw) => {
        const source = Array.isArray(raw) ? raw : [];
        return source.filter((card) => card && typeof card === 'object' && !Array.isArray(card)).slice(0, 12);
    };

    const chatMaterialStates = new Set([
        'AVAILABLE', 'CONFIRMATION_REQUIRED', 'QUEUED', 'RUNNING', 'READY', 'FAILED', 'EXPIRED'
    ]);
    const chatCardState = (card) => {
        const state = String(card.state || card.status || '').toUpperCase();
        return chatMaterialStates.has(state) ? state : '';
    };

    const scheduleChatMaterialPoll = (generationId, delay = 2000) => {
        const job = chatMaterialJobs.get(generationId);
        if (!job || job.paused || ['READY', 'FAILED', 'EXPIRED'].includes(job.state)) return;
        if (Date.now() - job.startedAt >= materialPollPolicy.MAX_TOTAL_MS) {
            const stateNode = job.node.querySelector('.chat-material-state');
            if (stateNode) stateNode.textContent = '自动刷新已暂停，可手动继续查询。';
            job.paused = true;
            const actions = job.node.querySelector('.chat-material-actions');
            actions.replaceChildren();
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'quiet';
            retry.textContent = '继续查询状态';
            retry.addEventListener('click', () => {
                job.paused = false;
                job.startedAt = Date.now();
                if (stateNode) stateNode.textContent = '正在重新查询生成状态…';
                actions.replaceChildren();
                scheduleChatMaterialPoll(generationId, 250);
            });
            actions.appendChild(retry);
            return;
        }
        if (job.timer !== null) window.clearTimeout(job.timer);
        job.timer = window.setTimeout(() => {
            job.timer = null;
            if (!chatMaterialJobs.has(generationId)) return;
            if (nativeBusy) {
                scheduleChatMaterialPoll(generationId, 1000);
                return;
            }
            invoke('MATERIAL_TEMPLATE_STATUS_GET', {generation_id: generationId}, {
                kind: 'chat_material_status', generationId, cardNode: job.node
            });
        }, Math.max(500, Number(delay) || 2000));
    };

    const updateChatMaterialCard = (node, card) => {
        if (!node || !card) return;
        const state = chatCardState(card);
        if (!state) return;
        const intentId = String(card.intent_id || node.dataset.intentId || '');
        const generationId = String(card.generation_id || card.id || node.dataset.generationId || '');
        node.dataset.state = state;
        node.dataset.intentId = canonicalUuid.test(intentId) ? intentId : '';
        node.dataset.generationId = canonicalUuid.test(generationId) ? generationId : '';
        const stateNode = node.querySelector('.chat-material-state');
        const labels = {
            AVAILABLE: '发现可生成模板',
            CONFIRMATION_REQUIRED: '等待确认',
            QUEUED: '已排队',
            RUNNING: '正在识别模板并生成 Word',
            READY: 'Word 已生成',
            FAILED: '生成失败',
            EXPIRED: '生成文件已过期'
        };
        stateNode.textContent = labels[state] || state;
        const actions = node.querySelector('.chat-material-actions');
        actions.replaceChildren();
        if (['AVAILABLE', 'CONFIRMATION_REQUIRED'].includes(state) && node.dataset.intentId) {
            const generate = document.createElement('button');
            generate.type = 'button';
            generate.className = 'link-button';
            generate.textContent = state === 'AVAILABLE' ? '生成此空白模板' : '确认生成';
            generate.addEventListener('click', () => {
                if (role !== 'CITIZEN') {
                    showAlert('请先登录群众账号，再生成并下载 Word。', 'info');
                    return;
                }
                if (node.dataset.confirming !== 'true') {
                    node.dataset.confirming = 'true';
                    stateNode.textContent = '请确认：将生成一份不绑定办件、需自行填写的空白演示模板。';
                    generate.textContent = '再次点击确认生成';
                    const cancel = document.createElement('button');
                    cancel.type = 'button';
                    cancel.className = 'quiet';
                    cancel.textContent = '取消';
                    cancel.addEventListener('click', () => updateChatMaterialCard(node, {...card, state}));
                    actions.append(generate, cancel);
                    return;
                }
                node.dataset.confirming = 'false';
                stateNode.textContent = '正在创建生成任务…';
                actions.replaceChildren();
                invoke('CONSULTATION_MATERIAL_CONFIRM', {
                    session_id: chatSessionId,
                    intent_id: node.dataset.intentId
                }, {kind: 'chat_material_confirm', cardNode: node});
            });
            actions.appendChild(generate);
        } else if (state === 'AVAILABLE' && role !== 'CITIZEN') {
            const login = document.createElement('button');
            login.type = 'button';
            login.className = 'quiet';
            login.textContent = '前往登录';
            login.addEventListener('click', () => selectSection('login'));
            actions.appendChild(login);
        } else if (state === 'READY' && node.dataset.generationId) {
            const save = document.createElement('button');
            save.type = 'button';
            save.className = 'link-button';
            save.textContent = '保存 Word 文档';
            save.addEventListener('click', () => {
                const nativeBridge = bridge();
                if (!nativeBridge || typeof nativeBridge.saveGeneratedDocument !== 'function') {
                    showAlert('原生 Word 保存服务尚未就绪');
                    return;
                }
                nativeBridge.saveGeneratedDocument(node.dataset.generationId);
            });
            actions.appendChild(save);
        } else if (state === 'FAILED' || state === 'EXPIRED') {
            const retry = document.createElement('span');
            retry.className = 'muted';
            retry.textContent = state === 'EXPIRED' ? '请在对话中重新请求生成。' : '本次任务失败，请稍后重新生成。';
            actions.appendChild(retry);
        }
        if (node.dataset.generationId && ['QUEUED', 'RUNNING'].includes(state)) {
            const existing = chatMaterialJobs.get(node.dataset.generationId);
            const job = existing || {node, timer: null, startedAt: Date.now(), state, paused: false};
            job.node = node;
            job.state = state;
            chatMaterialJobs.set(node.dataset.generationId, job);
            scheduleChatMaterialPoll(node.dataset.generationId,
                materialPollPolicy.delayForElapsed(Date.now() - job.startedAt));
        } else if (node.dataset.generationId) {
            const job = chatMaterialJobs.get(node.dataset.generationId);
            if (job && job.timer !== null) window.clearTimeout(job.timer);
            chatMaterialJobs.delete(node.dataset.generationId);
        }
    };

    const renderChatMaterialCard = (container, card) => {
        const type = String(card.type || card.card_type || '').toUpperCase();
        if (type !== 'MATERIAL_TEMPLATE' || !chatCardState(card)) return;
        const node = document.createElement('article');
        node.className = 'chat-material-card';
        const title = document.createElement('h4');
        title.textContent = String(card.template_title || card.requirement_name || card.title || '材料空白模板');
        const description = document.createElement('p');
        const service = card.service_title ? `${card.service_title} · ` : '';
        description.textContent = `${service}${card.notice || '生成后请自行核对和填写，仅供演示。'}`;
        const state = document.createElement('p');
        state.className = 'chat-material-state';
        const actions = document.createElement('div');
        actions.className = 'button-row wrap chat-material-actions';
        node.append(title, description, state, actions);
        container.appendChild(node);
        updateChatMaterialCard(node, card);
    };

    const renderTurnCards = (turn, cards) => {
        turn.cards.replaceChildren();
        normalizeUiCards(cards).forEach((card) => renderChatMaterialCard(turn.cards, card));
        scrollChatToEnd();
    };

    const updateChatStream = (state, data) => {
        const turn = ensureChatTurn(state.request_id || '', '');
        turn.actions.replaceChildren();
        const answer = data && typeof data.answer === 'string' ? data.answer : '';
        if (answer) {
            turn.answer = answer;
            turn.assistantBubble.textContent = answer;
        }
        const eventType = String(data && data.event_type || '');
        const payload = data && data.payload && typeof data.payload === 'object' ? data.payload : {};
        if (payload.session_id) {
            chatSessionId = String(payload.session_id);
            byId('handoff-session').value = chatSessionId;
            byId('feedback-session').value = chatSessionId;
        }
        if (eventType === 'done') {
            turn.assistantBubble.dataset.state = 'done';
            const cards = payload.ui_cards || payload.cards || [];
            renderTurnCards(turn, cards);
        } else {
            turn.assistantBubble.dataset.state = 'streaming';
        }
        const meta = {...payload};
        delete meta.ui_cards;
        delete meta.cards;
        if (Object.keys(meta).length) {
            turn.meta.hidden = false;
            turn.metaOutput.textContent = JSON.stringify(meta, null, 2);
        }
        scrollChatToEnd();
    };

    const renderChatRetry = (turn) => {
        if (!turn) return;
        turn.actions.replaceChildren();
        const message = String(turn.userBubble.textContent || '').trim();
        if (!message) return;
        const retry = document.createElement('button');
        retry.type = 'button';
        retry.className = 'quiet';
        retry.setAttribute('data-native-action', '');
        retry.textContent = '重试这条消息';
        retry.addEventListener('click', () => {
            retry.disabled = true;
            retry.textContent = '已重新发送';
            const requestId = nextRequestId();
            createChatTurn(requestId, message);
            const payload = {message};
            if (chatSessionId) payload.session_id = chatSessionId;
            invoke('CHAT_STREAM', payload, null, requestId);
        });
        turn.actions.appendChild(retry);
    };

    const renderConsultationHistory = (data) => {
        const target = byId('chat-history-list');
        target.replaceChildren();
        const items = dataItems(data);
        if (!items.length) {
            const empty = document.createElement('p');
            empty.className = 'muted';
            empty.textContent = '还没有可恢复的对话。';
            target.appendChild(empty);
            return;
        }
        items.forEach((item) => {
            const sessionId = String(item.id || item.session_id || '');
            if (!canonicalUuid.test(sessionId)) return;
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'quiet chat-history-item';
            button.setAttribute('data-native-action', '');
            const title = document.createElement('strong');
            title.textContent = String(item.title || item.last_message_preview || item.preview || '政务咨询');
            const detail = document.createElement('span');
            detail.textContent = `${Number(item.message_count || 0)} 条消息 · ${item.updated_at || item.created_at || ''}`;
            button.append(title, detail);
            button.addEventListener('click', () => {
                showAlert('正在加载历史消息…', 'info');
                invoke('CONSULTATION_MESSAGES', {session_id: sessionId, limit: '50'}, {
                    kind: 'chat_history_load', sessionId
                });
            });
            target.appendChild(button);
        });
    };

    const renderConsultationMessages = (data) => {
        const items = dataItems(data);
        clearChatTranscript(items.length ? '' : '这个对话还没有消息。');
        const empty = byId('chat-empty');
        if (empty && items.length) empty.remove();
        let pendingUser = null;
        items.forEach((message, index) => {
            const roleName = String(message.role || '').toLowerCase();
            if (roleName === 'user' || roleName === 'human') {
                pendingUser = message;
                return;
            }
            if (roleName !== 'assistant' && roleName !== 'ai') return;
            const requestId = String(message.request_id || message.id || `history-${index}`);
            const turn = createChatTurn(requestId, pendingUser ? String(pendingUser.content || '') : '', String(message.content || ''));
            turn.assistantBubble.dataset.state = 'done';
            const extra = message.extra && typeof message.extra === 'object' ? message.extra : {};
            renderTurnCards(turn, message.ui_cards || message.cards || extra.ui_cards || []);
            pendingUser = null;
        });
        if (pendingUser) createChatTurn(String(pendingUser.request_id || pendingUser.id || 'history-last'), String(pendingUser.content || ''), '该条消息尚无完整答复。').assistantBubble.dataset.state = 'error';
        scrollChatToEnd();
    };

    const clearMaterialTemplateSelection = (clearOptions = false) => {
        byId('requirement-id').value = '';
        byId('material-template-id').value = '';
        if (!clearOptions) return;
        const target = byId('material-template-options');
        target.replaceChildren();
        const message = document.createElement('p');
        message.className = 'muted';
        message.textContent = '请加载当前办件的材料模板。';
        target.appendChild(message);
    };

    const updateUser = (raw) => {
        const nextUser = normalizeUser(raw);
        const nextIdentityKey = `${String(nextUser.role).toUpperCase()}:${nextUser.id || ''}`;
        if (lastIdentityKey && nextIdentityKey !== lastIdentityKey) {
            chatSessionId = '';
            pendingHistoryRestoreSessionId = '';
            clearChatTranscript();
            byId('chat-history-list').replaceChildren();
        }
        lastIdentityKey = nextIdentityKey;
        user = nextUser;
        role = navigation[user.role] ? user.role : 'ANONYMOUS';
        byId('role-badge').textContent = {ANONYMOUS: '访客', CITIZEN: '群众', STAFF: '工作人员', ADMIN: '管理员'}[role];
        byId('display-name').textContent = role === 'ANONYMOUS' ? '未登录' : user.display_name;
        byId('logout-button').hidden = role === 'ANONYMOUS';
        byId('profile-output').textContent = JSON.stringify(user, null, 2);
        if (role !== 'CITIZEN') {
            stopMaterialPoll();
            materialGenerationId = '';
            materialGenerationStatus = '';
            materialPollPaused = false;
            materialPollStartedAt = 0;
            clearMaterialTemplateSelection(true);
            const card = byId('material-generation-card');
            if (card) card.hidden = true;
        }
        renderNavigation();
    };

    const dataItems = (data) => {
        if (Array.isArray(data)) return data;
        if (!data || typeof data !== 'object') return [];
        if (Array.isArray(data.items)) return data.items;
        if (data.data && Array.isArray(data.data.items)) return data.data.items;
        if (Array.isArray(data.services)) return data.services;
        if (Array.isArray(data.materials)) return data.materials;
        if (Array.isArray(data.requirements)) return data.requirements;
        return [];
    };

    const stopMaterialPoll = () => {
        if (materialPollTimer !== null) window.clearTimeout(materialPollTimer);
        materialPollTimer = null;
    };

    const pauseMaterialPoll = () => {
        stopMaterialPoll();
        materialPollPaused = true;
        const detail = byId('material-generation-detail');
        if (detail && !['READY', 'FAILED', 'EXPIRED'].includes(materialGenerationStatus)) {
            detail.textContent = '自动刷新已暂停，任务可能仍在后台运行。请点击“刷新状态”继续查询。';
        }
    };

    const resetMaterialPollWindow = () => {
        stopMaterialPoll();
        materialPollStartedAt = Date.now();
        materialPollPaused = false;
    };

    const scheduleMaterialPoll = (delay) => {
        stopMaterialPoll();
        const context = () => ({
            generationId: materialGenerationId,
            status: materialGenerationStatus,
            section: currentSection,
            startedAt: materialPollStartedAt,
            now: Date.now()
        });
        if (materialPollPaused) return;
        if (!materialPollPolicy.canPoll(context())) {
            if (materialGenerationId && currentSection === 'applications'
                && !['READY', 'FAILED', 'EXPIRED'].includes(materialGenerationStatus)) {
                pauseMaterialPoll();
            }
            return;
        }
        materialPollTimer = window.setTimeout(() => {
            materialPollTimer = null;
            if (!materialPollPolicy.canPoll(context())) {
                pauseMaterialPoll();
                return;
            }
            if (nativeBusy) {
                scheduleMaterialPoll(1000);
                return;
            }
            invoke('MATERIAL_TEMPLATE_STATUS_GET', {generation_id: materialGenerationId});
        }, Math.max(250, Number(delay) || 2000));
    };

    const materialPollDelay = () => materialPollPolicy.delayForElapsed(
        materialPollPolicy.elapsedMs(materialPollStartedAt, Date.now())
    );

    const renderMaterialOptions = (data) => {
        const target = byId('material-template-options');
        target.replaceChildren();
        const items = dataItems(data);
        if (!items.length) {
            const empty = document.createElement('p');
            empty.className = 'muted';
            empty.textContent = '该事项没有可展示的材料要求。';
            target.appendChild(empty);
            return;
        }
        items.forEach((item) => {
            const template = item && item.template && typeof item.template === 'object' ? item.template : {};
            const requirementCode = String(item.requirement_code || item.code || item.id || '');
            const templateId = String(item.template_id || template.id || '');
            const available = item.template_available === true || template.available === true;
            const mode = String(item.mode || item.template_mode || template.mode || 'NOT_GENERATABLE');
            const card = document.createElement('article');
            card.className = 'material-template-option';
            card.dataset.available = available ? 'true' : 'false';
            const title = document.createElement('strong');
            title.textContent = item.name || item.requirement_name || item.template_title
                || item.title || requirementCode || '未命名材料';
            const description = document.createElement('p');
            description.className = 'muted';
            description.textContent = item.notice || item.template_notice || template.notice
                || (available ? `可生成可编辑 Word · ${mode}` : '该材料属于证件或证明，不能由系统生成。');
            card.append(title, description);
            if (available && templateId && requirementCode) {
                const select = document.createElement('button');
                select.type = 'button';
                select.className = 'quiet';
                select.textContent = '选择此模板';
                select.addEventListener('click', () => {
                    byId('requirement-id').value = requirementCode;
                    byId('material-template-id').value = templateId;
                    selectSection('applications');
                    byId('material-template-request').focus({preventScroll: false});
                    showAlert(`已选择“${title.textContent}”，请核对补充要求后生成。`, 'info');
                });
                card.appendChild(select);
            }
            target.appendChild(card);
        });
    };

    const materialDocumentRoot = (data) => {
        if (!data || typeof data !== 'object') return {};
        if (data.document && typeof data.document === 'object') return data.document;
        if (data.data && typeof data.data === 'object') return data.data;
        return data;
    };

    const handleMaterialGeneration = (data) => {
        const document = materialDocumentRoot(data);
        const generationId = String(document.generation_id || document.id || materialGenerationId || '');
        if (generationId) materialGenerationId = generationId;
        materialGenerationStatus = String(document.status || document.state || materialGenerationStatus || 'QUEUED').toUpperCase();
        if (!materialPollStartedAt) materialPollStartedAt = Date.now();
        const card = byId('material-generation-card');
        const state = byId('material-generation-state');
        const detail = byId('material-generation-detail');
        const save = byId('material-generation-save');
        byId('material-generation-id').value = materialGenerationId;
        card.hidden = false;
        const labels = {
            QUEUED: '已排队，等待生成',
            RUNNING: '正在识别模板并生成 Word',
            READY: 'Word 已生成，可以保存',
            FAILED: '生成失败',
            EXPIRED: '生成文件已过期'
        };
        state.textContent = labels[materialGenerationStatus] || `任务状态：${materialGenerationStatus}`;
        const filename = document.filename || document.file_name || document.display_name || '';
        const expires = document.expires_at || '';
        const failure = document.failure_message || document.message
            || (document.error_code ? `失败代码：${document.error_code}` : '');
        detail.textContent = materialGenerationStatus === 'READY'
            ? `${filename || '可填写材料.docx'}${expires ? ` · ${expires} 前可下载` : ''}`
            : (failure || '任务在后台运行，离开本页不会中断生成。');
        save.disabled = materialGenerationStatus !== 'READY';
        if (['READY', 'FAILED', 'EXPIRED'].includes(materialGenerationStatus)) {
            materialPollPaused = false;
            stopMaterialPoll();
        }
        else scheduleMaterialPoll(materialPollDelay());
    };

    const renderServices = (data) => {
        const list = byId('service-results');
        list.replaceChildren();
        const items = dataItems(data);
        if (!items.length) {
            const empty = document.createElement('p');
            empty.className = 'muted';
            empty.textContent = '未查询到事项。';
            list.appendChild(empty);
            return;
        }
        items.forEach((item) => {
            const id = String(item.id || item.service_id || item.code || '');
            const card = document.createElement('article');
            card.className = 'service-card';
            const title = document.createElement('h3');
            title.textContent = item.name || item.title || item.service_name || '未命名事项';
            const summary = document.createElement('p');
            summary.textContent = item.summary || item.description || `事项编号：${id}`;
            const actions = document.createElement('div');
            actions.className = 'button-row wrap';
            const details = document.createElement('button');
            details.type = 'button';
            details.textContent = '查看详情';
            details.addEventListener('click', () => {
                byId('service-id').value = id;
                byId('application-service-id').value = id;
                byId('appointment-service').value = id;
                byId('service-navigation-id').value = id;
                invoke('CATALOG_DETAILS', {service_id: id});
            });
            actions.appendChild(details);
            if (role === 'CITIZEN') {
                const create = document.createElement('button');
                create.type = 'button';
                create.className = 'secondary';
                create.textContent = '创建办件';
                create.addEventListener('click', () => {
                    byId('application-service-id').value = id;
                    invoke('APPLICATION_CREATE', {service_id: id});
                });
                actions.appendChild(create);
            }
            card.append(title, summary, actions);
            list.appendChild(card);
        });
    };

    const findId = (data, ...keys) => {
        const source = data && data.data && typeof data.data === 'object' ? data.data : data;
        if (!source || typeof source !== 'object') return '';
        for (const key of keys) if (source[key]) return String(source[key]);
        return '';
    };

    const captureKnowledgeJob = (value) => {
        if (!value || typeof value !== 'object') return '';
        const candidates = [
            value,
            value.data,
            value.details,
            value.detail,
            value.error,
            value.error && value.error.details,
            value.error && value.error.detail
        ];
        for (const candidate of candidates) {
            if (candidate && typeof candidate === 'object' && candidate.job_id) {
                const jobId = String(candidate.job_id);
                byId('admin-knowledge-job').value = jobId;
                return jobId;
            }
        }
        return '';
    };

    const handleResult = (state) => {
        const data = state.data === null || state.data === undefined ? {} : state.data;
        const requestContext = pendingRequests.get(String(state.request_id || '')) || null;
        captureKnowledgeJob(data);
        activityOutput.textContent = JSON.stringify({command: state.command, phase: state.phase, data}, null, 2);
        switch (state.command) {
            case 'CATALOG_SEARCH': renderServices(data); break;
            case 'MATERIALS_GET':
            case 'MATERIAL_TEMPLATE_OPTIONS_GET': renderMaterialOptions(data); break;
            case 'APPLICATION_CREATE': {
                const id = findId(data, 'id', 'application_id');
                if (id) {
                    clearMaterialTemplateSelection(true);
                    byId('application-id').value = id;
                    byId('payment-application').value = id;
                    byId('verification-application').value = id;
                }
                const version = findId(data, 'version');
                if (version) byId('application-version').value = version;
                break;
            }
            case 'APPLICATION_DETAILS': {
                const version = findId(data, 'version');
                if (version) byId('application-version').value = version;
                const id = findId(data, 'id', 'application_id');
                if (id) {
                    byId('payment-application').value = id;
                    byId('verification-application').value = id;
                }
                const serviceId = findId(data, 'service_id');
                if (serviceId) byId('application-service-id').value = serviceId;
                break;
            }
            case 'MATERIAL_TEMPLATE_GENERATE':
                handleMaterialGeneration(data);
                break;
            case 'MATERIAL_TEMPLATE_STATUS_GET':
                if (requestContext && requestContext.kind === 'chat_material_status') {
                    const document = materialDocumentRoot(data);
                    updateChatMaterialCard(requestContext.cardNode, document);
                    pendingRequests.delete(String(state.request_id || ''));
                } else handleMaterialGeneration(data);
                break;
            case 'CONSULTATION_HISTORY':
                renderConsultationHistory(data);
                pendingRequests.delete(String(state.request_id || ''));
                break;
            case 'CONSULTATION_MESSAGES':
                if (!requestContext || requestContext.kind !== 'chat_history_load'
                    || !canonicalUuid.test(String(requestContext.sessionId || ''))) {
                    pendingRequests.delete(String(state.request_id || ''));
                    break;
                }
                if (data.session_id && String(data.session_id) !== requestContext.sessionId) {
                    if (pendingHistoryRestoreSessionId === requestContext.sessionId) {
                        pendingHistoryRestoreSessionId = '';
                    }
                    showAlert('历史会话校验失败，请重新选择。');
                    pendingRequests.delete(String(state.request_id || ''));
                    break;
                }
                chatSessionId = requestContext.sessionId;
                if (pendingHistoryRestoreSessionId === chatSessionId) pendingHistoryRestoreSessionId = '';
                renderConsultationMessages(data);
                pendingRequests.delete(String(state.request_id || ''));
                break;
            case 'CONSULTATION_MATERIAL_CONFIRM': {
                const document = materialDocumentRoot(data);
                if (requestContext && requestContext.cardNode) {
                    updateChatMaterialCard(requestContext.cardNode, {
                        ...document,
                        state: document.status || document.state || 'QUEUED'
                    });
                }
                pendingRequests.delete(String(state.request_id || ''));
                break;
            }
            case 'WINDOW_LIST': {
                const first = dataItems(data)[0];
                const id = first ? String(first.id || first.window_id || '') : '';
                if (id) {
                    byId('appointment-window').value = id;
                }
                break;
            }
            case 'PAYMENT_CREATE': {
                const id = findId(data, 'id', 'payment_id');
                if (id) byId('payment-id').value = id;
                break;
            }
            case 'DELIVERY_SET': {
                const id = findId(data, 'id', 'delivery_id');
                if (id) byId('delivery-id').value = id;
                break;
            }
            case 'VERIFICATION_CREATE': {
                const id = findId(data, 'id', 'verification_id');
                if (id) byId('verification-id').value = id;
                break;
            }
            case 'APPOINTMENT_BOOK': {
                const id = findId(data, 'id', 'appointment_id');
                if (id) byId('appointment-id').value = id;
                break;
            }
            case 'HANDOFF_CREATE': {
                const id = findId(data, 'id', 'ticket_id');
                if (id) byId('citizen-ticket-id').value = id;
                break;
            }
            case 'CHAT_STREAM': {
                updateChatStream(state, data);
                if (data.event_type === 'done') {
                    pendingRequests.delete(String(state.request_id || ''));
                    if (role === 'CITIZEN' && canonicalUuid.test(pendingHistoryRestoreSessionId)) {
                        const sessionId = pendingHistoryRestoreSessionId;
                        pendingHistoryRestoreSessionId = '';
                        invoke('CONSULTATION_MESSAGES', {session_id: sessionId, limit: '50'}, {
                            kind: 'chat_history_load', sessionId, automatic: true
                        });
                    }
                }
                break;
            }
            case 'CHAT_SESSION_RESET':
                chatSessionId = '';
                pendingHistoryRestoreSessionId = '';
                clearChatTranscript();
                byId('chat-message').value = '';
                break;
            case 'AUTH_LOGIN':
                if (state.phase === 'success') {
                    showAlert('登录成功。', 'success');
                    currentSection = role === 'CITIZEN' ? 'consultation' : (navigation[role] || navigation.ANONYMOUS)[0][0];
                    renderNavigation();
                }
                break;
            case 'AUTH_SEND_CODE':
                if (state.phase === 'success' && data && typeof data.demo_code === 'string'
                    && /^\d{4,12}$/.test(data.demo_code)) {
                    byId('register-code').value = data.demo_code;
                    showAlert('演示验证码已自动填入，请提交注册。', 'success');
                }
                break;
            case 'AUTH_LOGOUT':
                if (state.phase === 'success') { currentSection = 'consultation'; showAlert('已退出登录。', 'success'); }
                break;
            case 'AUTH_REGISTER':
                if (state.phase === 'success') {
                    showAlert(role === 'CITIZEN' ? '注册并登录成功。' : '注册成功，请使用新账号登录。', 'success');
                    if (role === 'CITIZEN') { currentSection = 'consultation'; renderNavigation(); }
                }
                break;
            default: break;
        }
    };

    window.GovPortal = Object.freeze({
        onNativeReady(payload) {
            byId('native-status').textContent = `${payload.hms_status || 'Android 服务已连接'} · 本地演示后端`;
            updateUser(payload.user);
            if (payload.chat_session_id && canonicalUuid.test(String(payload.chat_session_id))) {
                chatSessionId = String(payload.chat_session_id);
                if (role === 'CITIZEN') {
                    pendingHistoryRestoreSessionId = chatSessionId;
                    invoke('CONSULTATION_MESSAGES', {session_id: chatSessionId, limit: '50'}, {
                        kind: 'chat_history_load', sessionId: chatSessionId, automatic: true
                    });
                }
            }
            if (payload.material_generation_id) {
                materialGenerationId = String(payload.material_generation_id);
                materialGenerationStatus = 'QUEUED';
                resetMaterialPollWindow();
                handleMaterialGeneration({generation_id: materialGenerationId, status: 'QUEUED'});
            }
        },
        onNativeState(state) {
            if (!state || typeof state !== 'object') return;
            updateUser(state.user);
            setBusy(Boolean(state.busy));
            if (state.phase === 'loading' && state.command === 'CHAT_STREAM') {
                ensureChatTurn(String(state.request_id || ''), byId('chat-message').value.trim());
                return;
            }
            if (state.phase === 'error') {
                captureKnowledgeJob(state.error);
                showAlert(state.error && state.error.message ? state.error.message : '操作失败');
                activityOutput.textContent = JSON.stringify({command: state.command, error: state.error}, null, 2);
                const requestContext = pendingRequests.get(String(state.request_id || '')) || null;
                if (state.command === 'CHAT_STREAM') {
                    const turn = ensureChatTurn(String(state.request_id || ''), byId('chat-message').value.trim());
                    turn.assistantBubble.dataset.state = 'error';
                    turn.assistantBubble.textContent = state.error && state.error.message
                        ? state.error.message : '这条消息暂时没有发送成功，请重试。';
                    renderChatRetry(turn);
                } else if (state.command === 'CONSULTATION_MESSAGES' && requestContext
                    && requestContext.kind === 'chat_history_load') {
                    const statusCode = Number(state.error && (state.error.status_code || state.error.statusCode) || 0);
                    if (requestContext.automatic && statusCode === 409) {
                        pendingHistoryRestoreSessionId = requestContext.sessionId;
                        showAlert('当前回答完成后将恢复历史消息。', 'info');
                    } else {
                        if (pendingHistoryRestoreSessionId === requestContext.sessionId) {
                            pendingHistoryRestoreSessionId = '';
                        }
                        showAlert('历史消息加载失败，当前对话没有切换。');
                    }
                } else if (state.command === 'CONSULTATION_MATERIAL_CONFIRM' && requestContext && requestContext.cardNode) {
                    requestContext.cardNode.dataset.confirming = 'false';
                    updateChatMaterialCard(requestContext.cardNode, {
                        intent_id: requestContext.cardNode.dataset.intentId,
                        state: 'CONFIRMATION_REQUIRED'
                    });
                } else if (state.command === 'MATERIAL_TEMPLATE_STATUS_GET' && requestContext
                    && requestContext.kind === 'chat_material_status') {
                    const statusCode = Number(state.error && (state.error.status_code || state.error.statusCode) || 0);
                    if ([404, 410].includes(statusCode)) {
                        updateChatMaterialCard(requestContext.cardNode, {
                            generation_id: requestContext.generationId,
                            state: statusCode === 410 ? 'EXPIRED' : 'FAILED'
                        });
                    } else scheduleChatMaterialPoll(requestContext.generationId, 3000);
                } else if (state.command === 'MATERIAL_TEMPLATE_STATUS_GET') {
                    const statusCode = Number(state.error && (state.error.status_code || state.error.statusCode) || 0);
                    if (statusCode === 401 || statusCode === 404 || statusCode === 410) {
                        materialGenerationStatus = statusCode === 410 ? 'EXPIRED' : 'FAILED';
                        handleMaterialGeneration({
                            generation_id: materialGenerationId,
                            status: materialGenerationStatus,
                            failure_message: state.error && state.error.message
                        });
                    } else {
                        scheduleMaterialPoll(materialPollDelay());
                    }
                } else if (state.command === 'MATERIAL_TEMPLATE_GENERATE') {
                    materialGenerationStatus = 'FAILED';
                    byId('material-generation-card').hidden = false;
                    byId('material-generation-state').textContent = '未能创建生成任务';
                    byId('material-generation-detail').textContent = state.error && state.error.message
                        ? state.error.message : '请核对办件状态和模板后重试。';
                    byId('material-generation-save').disabled = true;
                }
                pendingRequests.delete(String(state.request_id || ''));
                return;
            }
            if (state.phase !== 'loading' && state.phase !== 'idle') handleResult(state);
        },
        onNativeAux(event) {
            if (!event || typeof event !== 'object') return;
            if (event.type === 'voice_partial' || event.type === 'voice_final') {
                byId('chat-message').value = event.text || '';
            }
            if (event.type === 'voice_state') byId('voice-status').textContent = `语音状态：${event.state}`;
            if (event.type === 'boundary_error') showAlert(event.message || '原生能力调用失败');
            if (event.type === 'document_cancelled') showAlert('已取消文件选择。', 'info');
            if (event.type === 'material_document_preparing') showAlert('正在安全下载并校验 Word 文件…', 'info');
            if (event.type === 'material_document_save_cancelled') showAlert('已取消保存 Word 文件。', 'info');
            if (event.type === 'material_document_saved') {
                showAlert(event.opened
                    ? `已保存并打开 ${event.display_name || 'Word 文件'}。`
                    : `已保存 ${event.display_name || 'Word 文件'}；设备未安装可打开 DOCX 的应用。`, 'success');
            }
            if (event.type === 'digital_human_intent') applyDigitalHumanIntent(event);
        }
    });

    bindSubmit('chat-form', () => {
        const message = requiredValue('chat-message', '咨询内容');
        const requestId = nextRequestId();
        createChatTurn(requestId, message);
        byId('chat-message').value = '';
        const payload = {message};
        if (chatSessionId) payload.session_id = chatSessionId;
        invoke('CHAT_STREAM', payload, null, requestId);
    });
    bindClick('chat-new', () => {
        invoke('CHAT_SESSION_RESET');
    });
    bindClick('chat-history-toggle', () => {
        if (role !== 'CITIZEN') throw new Error('请先登录后查看历史对话');
        const panel = byId('chat-history-panel');
        panel.hidden = !panel.hidden;
        if (!panel.hidden) invoke('CONSULTATION_HISTORY', {limit: '20'});
    });
    bindClick('voice-start', () => bridge() ? bridge().voice('start') : showAlert('原生服务未就绪'));
    bindClick('voice-stop', () => bridge() ? bridge().voice('stop') : showAlert('原生服务未就绪'));
    bindClick('logout-button', () => invoke('AUTH_LOGOUT'));
    bindClick('login-show-register', () => {
        const form = byId('register-form');
        form.scrollIntoView({behavior: 'smooth', block: 'start'});
        byId('register-account').focus({preventScroll: true});
    });

    bindSubmit('login-form', () => invoke('AUTH_LOGIN', {username: requiredValue('login-account', '账号'), password: requiredValue('login-password', '密码')}));
    bindClick('send-code', () => invoke('AUTH_SEND_CODE', {destination: requiredValue('register-account', '注册账号'), purpose: 'REGISTER'}));
    bindSubmit('register-form', () => invoke('AUTH_REGISTER', {
        username: requiredValue('register-account', '注册账号'),
        display_name: requiredValue('register-name', '显示名称'),
        applicant_type: byId('register-type').value,
        password: requiredValue('register-password', '密码'),
        verification_code: requiredValue('register-code', '验证码'),
        synthetic_data_confirmed: true
    }));

    bindSubmit('service-search-form', () => invoke('CATALOG_SEARCH', {query: byId('service-query').value.trim(), applicant_type: byId('service-applicant').value}));
    const servicePayload = () => ({service_id: requiredValue('service-id', '事项编号')});
    bindClick('service-details', () => invoke('CATALOG_DETAILS', servicePayload()));
    bindClick('service-eligibility', () => invoke('ELIGIBILITY_CHECK', {...servicePayload(), answers: safeJson(byId('eligibility-json').value)}));
    bindClick('service-materials', () => invoke('MATERIALS_GET', servicePayload()));
    bindClick('service-process', () => invoke('PROCESS_GET', servicePayload()));
    bindClick('service-form-schema', () => invoke('FORM_SCHEMA_GET', servicePayload()));
    bindClick('service-windows', () => invoke('WINDOW_LIST', servicePayload()));
    bindSubmit('service-navigation-form', () => {
        const serviceId = requiredValue('service-navigation-id', '事项 UUID');
        if (!canonicalUuid.test(serviceId)) throw new Error('事项编号必须是标准小写 UUID');
        if (!bridge() || typeof bridge().openServiceNavigation !== 'function') return showAlert('原生导航服务未就绪');
        bridge().openServiceNavigation(serviceId);
    });
    bindClick('digital-human-navigation-confirm', () => {
        if (!canonicalUuid.test(pendingNavigationServiceId)) throw new Error('待确认的事项编号已失效');
        if (!bridge() || typeof bridge().openServiceNavigation !== 'function') return showAlert('原生导航服务未就绪');
        const serviceId = pendingNavigationServiceId;
        pendingNavigationServiceId = '';
        byId('digital-human-navigation-confirmation').hidden = true;
        bridge().openServiceNavigation(serviceId);
    });
    bindClick('digital-human-navigation-cancel', () => {
        pendingNavigationServiceId = '';
        byId('digital-human-navigation-confirmation').hidden = true;
    });

    bindSubmit('handoff-form', () => invoke('HANDOFF_CREATE', {session_id: requiredValue('handoff-session', '咨询会话编号'), subject: requiredValue('handoff-reason', '问题说明')}));
    bindSubmit('feedback-form', () => invoke('CONSULTATION_FEEDBACK', {session_id: requiredValue('feedback-session', '会话编号'), rating: Number(byId('feedback-rating').value), comment: byId('feedback-comment').value.trim()}));
    bindClick('consultation-history', () => {
        byId('chat-history-panel').hidden = false;
        invoke('CONSULTATION_HISTORY', {limit: '20'});
    });
    bindClick('handoff-messages', () => invoke('HANDOFF_MESSAGES', {ticket_id: requiredValue('citizen-ticket-id', '工单编号')}));
    bindClick('handoff-message-add', () => invoke('HANDOFF_MESSAGE_ADD', {ticket_id: requiredValue('citizen-ticket-id', '工单编号'), content: requiredValue('citizen-handoff-content', '消息内容')}));
    bindClick('handoff-cancel', () => invoke('HANDOFF_CANCEL', {ticket_id: requiredValue('citizen-ticket-id', '工单编号')}));

    bindSubmit('application-create-form', () => invoke('APPLICATION_CREATE', {service_id: requiredValue('application-service-id', '事项编号')}));
    bindClick('application-list', () => invoke('APPLICATION_LIST'));
    const applicationPayload = () => ({application_id: requiredValue('application-id', '办件编号'), version: Number(requiredValue('application-version', '当前版本号'))});
    bindClick('application-details', () => invoke('APPLICATION_DETAILS', applicationPayload()));
    bindClick('application-timeline', () => invoke('APPLICATION_TIMELINE', applicationPayload()));
    bindClick('application-withdraw', () => invoke('APPLICATION_WITHDRAW', {...applicationPayload(), comment: '群众主动撤回'}));
    bindClick('application-discard', () => invoke('APPLICATION_DISCARD', {...applicationPayload(), comment: '群众丢弃草稿'}));
    bindClick('application-save-form', () => invoke('APPLICATION_UPDATE_FORM', {...applicationPayload(), data: safeJson(byId('application-form-json').value)}));
    bindClick('application-submit', () => invoke('APPLICATION_SUBMIT', applicationPayload()));
    bindClick('material-pick', () => {
        if (!bridge()) return showAlert('原生服务未就绪');
        bridge().chooseDocument(JSON.stringify({purpose: 'material', application_id: requiredValue('application-id', '办件编号'), requirement_id: requiredValue('requirement-id', '材料要求编号')}));
    });
    bindClick('material-template-load', () => invoke('MATERIAL_TEMPLATE_OPTIONS_GET', {
        application_id: (() => {
            const applicationId = requiredValue('application-id', '办件编号');
            clearMaterialTemplateSelection(true);
            byId('material-template-options').firstElementChild.textContent = '正在加载当前办件的材料模板…';
            return applicationId;
        })()
    }));
    bindClick('material-template-generate', () => {
        const requestText = byId('material-template-request').value.trim();
        if (Array.from(requestText).length > 300) throw new Error('补充生成要求不能超过 300 字');
        materialGenerationId = '';
        materialGenerationStatus = 'QUEUED';
        resetMaterialPollWindow();
        byId('material-generation-card').hidden = false;
        byId('material-generation-state').textContent = '正在创建生成任务';
        byId('material-generation-detail').textContent = '正在保存本次合成演示表单快照。';
        byId('material-generation-id').value = '';
        byId('material-generation-save').disabled = true;
        invoke('MATERIAL_TEMPLATE_GENERATE', {
            application_id: requiredValue('application-id', '办件编号'),
            requirement_code: requiredValue('requirement-id', '材料要求编号'),
            template_id: requiredValue('material-template-id', '模板编号'),
            request_text: requestText
        });
    });
    bindClick('material-generation-refresh', () => {
        materialGenerationId = requiredValue('material-generation-id', '生成任务编号');
        resetMaterialPollWindow();
        invoke('MATERIAL_TEMPLATE_STATUS_GET', {generation_id: materialGenerationId});
    });
    bindClick('material-generation-save', () => {
        if (materialGenerationStatus !== 'READY') throw new Error('Word 尚未生成完成');
        const nativeBridge = bridge();
        if (!nativeBridge || typeof nativeBridge.saveGeneratedDocument !== 'function') {
            throw new Error('原生 Word 保存服务尚未就绪');
        }
        nativeBridge.saveGeneratedDocument(requiredValue('material-generation-id', '生成任务编号'));
    });
    byId('application-id').addEventListener('input', () => clearMaterialTemplateSelection(true));

    bindSubmit('appointment-form', () => invoke('APPOINTMENT_BOOK', {service_id: requiredValue('appointment-service', '事项编号'), window_id: requiredValue('appointment-window', '窗口编号'), slot_start: requiredValue('appointment-time', '预约时间')}));
    bindClick('appointment-list', () => invoke('APPOINTMENT_LIST'));
    bindClick('appointment-cancel', () => invoke('APPOINTMENT_CANCEL', {appointment_id: requiredValue('appointment-id', '预约编号')}));
    bindClick('payment-create', () => invoke('PAYMENT_CREATE', {application_id: requiredValue('payment-application', '办件编号')}));
    bindClick('payment-confirm', () => invoke('PAYMENT_CONFIRM', {payment_id: requiredValue('payment-id', '支付单编号'), outcome: 'success'}));
    bindClick('payment-cancel', () => invoke('PAYMENT_CANCEL', {payment_id: requiredValue('payment-id', '支付单编号')}));
    bindClick('verification-create', () => invoke('VERIFICATION_CREATE', {application_id: requiredValue('verification-application', '办件编号')}));
    bindClick('verification-confirm', () => invoke('VERIFICATION_CONFIRM', {verification_id: requiredValue('verification-id', '核验编号'), outcome: 'pass'}));
    bindSubmit('delivery-form', () => invoke('DELIVERY_SET', {...applicationPayload(), recipient: requiredValue('delivery-recipient', '收件人'), address: requiredValue('delivery-address', '演示地址')}));
    bindClick('delivery-cancel', () => invoke('DELIVERY_CANCEL', {delivery_id: requiredValue('delivery-id', '邮寄单编号')}));

    bindClick('staff-load-tasks', () => invoke('STAFF_TASKS'));
    bindSubmit('staff-claim-form', () => invoke('STAFF_CLAIM', {task_id: requiredValue('staff-task-id', '任务编号')}));
    const reviewPayload = () => ({application_id: requiredValue('staff-application-id', '办件编号'), version: Number(requiredValue('staff-version', '当前版本号')), comment: byId('staff-reason').value.trim(), require_payment: byId('staff-require-payment').checked});
    bindClick('staff-supplement', () => invoke('STAFF_SUPPLEMENT', reviewPayload()));
    bindClick('staff-approve', () => invoke('STAFF_APPROVE', reviewPayload()));
    bindClick('staff-reject', () => invoke('STAFF_REJECT', reviewPayload()));
    bindClick('staff-complete', () => invoke('STAFF_COMPLETE', reviewPayload()));
    bindClick('staff-load-handoffs', () => invoke('STAFF_HANDOFFS'));
    bindSubmit('staff-handoff-reply-form', () => invoke('STAFF_HANDOFF_REPLY', {ticket_id: requiredValue('staff-ticket-id', '工单编号'), content: requiredValue('staff-reply', '回复内容')}));
    bindClick('staff-handoff-resolve', () => invoke('STAFF_HANDOFF_RESOLVE', {ticket_id: requiredValue('staff-ticket-id', '工单编号')}));

    bindClick('admin-metrics', () => invoke('ADMIN_METRICS'));
    bindClick('admin-services', () => invoke('ADMIN_SERVICES'));
    bindSubmit('admin-service-form', () => invoke('ADMIN_SERVICE_CREATE', {title: requiredValue('admin-service-name', '事项名称'), code: requiredValue('admin-service-code', '事项代码'), department_id: requiredValue('admin-service-department', '部门编号'), applicant_type: byId('admin-service-applicant').value, summary: requiredValue('admin-service-summary', '事项说明')}));
    bindSubmit('admin-lifecycle-form', () => {
        const payload = {service_id: requiredValue('admin-service-id', '事项编号'), target_status: byId('admin-lifecycle-action').value};
        const versionId = byId('admin-version-id').value.trim();
        if (versionId) payload.version_id = versionId;
        invoke('ADMIN_SERVICE_LIFECYCLE', payload);
    });
    bindClick('admin-version-create', () => invoke('ADMIN_SERVICE_VERSION', {service_id: requiredValue('admin-service-id', '事项编号'), ...safeJson(byId('admin-version-json').value)}));
    bindClick('admin-departments', () => invoke('ADMIN_DEPARTMENTS'));
    bindClick('admin-windows', () => invoke('ADMIN_WINDOWS'));
    bindClick('admin-accounts', () => invoke('ADMIN_ACCOUNTS'));
    bindSubmit('admin-department-form', () => invoke('ADMIN_DEPARTMENT_CREATE', {code: requiredValue('admin-department-code', '部门代码'), name: requiredValue('admin-department-name', '部门名称')}));
    bindSubmit('admin-window-form', () => invoke('ADMIN_WINDOW_CREATE', {department_id: requiredValue('admin-window-department', '部门编号'), code: requiredValue('admin-window-code', '窗口代码'), name: requiredValue('admin-window-name', '窗口名称'), address: requiredValue('admin-window-address', '演示地址'), latitude: Number(requiredValue('admin-window-latitude', '纬度')), longitude: Number(requiredValue('admin-window-longitude', '经度'))}));
    bindSubmit('admin-staff-form', () => {
        const payload = {username: requiredValue('admin-staff-account', '工作人员账号'), password: requiredValue('admin-staff-password', '初始密码'), display_name: requiredValue('admin-staff-name', '工作人员姓名'), department_id: requiredValue('admin-department-id', '部门编号')};
        const windowId = byId('admin-staff-window').value.trim();
        if (windowId) payload.window_id = windowId;
        invoke('ADMIN_STAFF_CREATE', payload);
    });
    bindSubmit('admin-freeze-form', () => invoke('ADMIN_USER_FREEZE', {account_id: requiredValue('admin-user-id', '账号编号'), active: !byId('admin-freeze-value').checked}));
    bindClick('knowledge-pick', () => bridge() ? bridge().chooseDocument(JSON.stringify({purpose: 'knowledge'})) : showAlert('原生服务未就绪'));
    bindClick('admin-knowledge-retry', () => invoke('ADMIN_KNOWLEDGE_RETRY', {job_id: requiredValue('admin-knowledge-job', '索引任务编号')}));
    bindClick('admin-knowledge-archive', () => invoke('ADMIN_KNOWLEDGE_ARCHIVE', {job_id: requiredValue('admin-knowledge-job', '索引任务编号')}));
    bindClick('admin-audit', () => invoke('ADMIN_AUDIT'));
    bindClick('activity-clear', () => { activityOutput.textContent = '等待操作。'; clearAlert(); });

    renderNavigation();
})();
