(() => {
    'use strict';

    const byId = (id) => document.getElementById(id);
    const bridge = () => window.GovPortalNative;
    const activityOutput = byId('activity-output');
    const alertBox = byId('global-alert');
    let requestCounter = 0;
    let role = 'ANONYMOUS';
    let user = {role: 'ANONYMOUS', display_name: '访客', applicant_type: 'NONE'};
    let currentSection = 'consultation';

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

    const invoke = (command, payload = {}) => {
        clearAlert();
        const nativeBridge = bridge();
        if (!nativeBridge || typeof nativeBridge.execute !== 'function') {
            showAlert('Android 原生服务尚未就绪。');
            return;
        }
        nativeBridge.execute(JSON.stringify({request_id: nextRequestId(), command, payload}));
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
        document.querySelectorAll('[data-section]').forEach((element) => {
            element.hidden = element.dataset.section !== currentSection;
        });
        document.querySelectorAll('#primary-nav button').forEach((button) => {
            button.setAttribute('aria-current', button.dataset.section === currentSection ? 'page' : 'false');
        });
    };

    const applyDigitalHumanIntent = (event) => {
        if (!event.requires_confirmation || typeof event.section !== 'string') {
            showAlert('数字人操作建议未通过确认策略。');
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
            service_id: ['service-id', 'application-service-id', 'appointment-service', 'admin-service-id'],
            applicant_type: ['service-applicant'],
            account: ['login-account'],
            application_id: ['application-id', 'payment-application', 'verification-application'],
            requirement_id: ['requirement-id'],
            application_version: ['application-version'],
            payment_id: ['payment-id'],
            verification_id: ['verification-id'],
            delivery_id: ['delivery-id'],
            window_id: ['window-id', 'appointment-window', 'admin-window-id'],
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

    const updateUser = (raw) => {
        user = normalizeUser(raw);
        role = navigation[user.role] ? user.role : 'ANONYMOUS';
        byId('role-badge').textContent = {ANONYMOUS: '访客', CITIZEN: '群众', STAFF: '工作人员', ADMIN: '管理员'}[role];
        byId('display-name').textContent = role === 'ANONYMOUS' ? '未登录' : user.display_name;
        byId('logout-button').hidden = role === 'ANONYMOUS';
        byId('profile-output').textContent = JSON.stringify(user, null, 2);
        renderNavigation();
    };

    const dataItems = (data) => {
        if (Array.isArray(data)) return data;
        if (!data || typeof data !== 'object') return [];
        if (Array.isArray(data.items)) return data.items;
        if (data.data && Array.isArray(data.data.items)) return data.data.items;
        if (Array.isArray(data.services)) return data.services;
        return [];
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
        captureKnowledgeJob(data);
        activityOutput.textContent = JSON.stringify({command: state.command, phase: state.phase, data}, null, 2);
        switch (state.command) {
            case 'CATALOG_SEARCH': renderServices(data); break;
            case 'APPLICATION_CREATE': {
                const id = findId(data, 'id', 'application_id');
                if (id) {
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
                break;
            }
            case 'WINDOW_LIST': {
                const first = dataItems(data)[0];
                const id = first ? String(first.id || first.window_id || '') : '';
                if (id) {
                    byId('window-id').value = id;
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
                const answer = data && typeof data.answer === 'string' ? data.answer : '';
                if (answer) byId('chat-answer').textContent = answer;
                byId('chat-metadata').textContent = JSON.stringify(data.payload || {}, null, 2);
                if (data.event_type === 'meta' && data.payload && data.payload.session_id) {
                    byId('handoff-session').value = String(data.payload.session_id);
                    byId('feedback-session').value = String(data.payload.session_id);
                }
                break;
            }
            case 'AUTH_LOGIN':
                if (state.phase === 'success') {
                    showAlert('登录成功。', 'success');
                    currentSection = role === 'CITIZEN' ? 'consultation' : (navigation[role] || navigation.ANONYMOUS)[0][0];
                    renderNavigation();
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
        },
        onNativeState(state) {
            if (!state || typeof state !== 'object') return;
            updateUser(state.user);
            setBusy(Boolean(state.busy));
            if (state.phase === 'error') {
                captureKnowledgeJob(state.error);
                showAlert(state.error && state.error.message ? state.error.message : '操作失败');
                activityOutput.textContent = JSON.stringify({command: state.command, error: state.error}, null, 2);
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
            if (event.type === 'digital_human_intent') applyDigitalHumanIntent(event);
        }
    });

    bindSubmit('chat-form', () => invoke('CHAT_STREAM', {message: requiredValue('chat-message', '咨询内容')}));
    bindClick('voice-start', () => bridge() ? bridge().voice('start') : showAlert('原生服务未就绪'));
    bindClick('voice-stop', () => bridge() ? bridge().voice('stop') : showAlert('原生服务未就绪'));
    bindClick('logout-button', () => invoke('AUTH_LOGOUT'));

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
    bindSubmit('window-map-form', () => bridge() ? bridge().openWindowMap(requiredValue('window-id', '窗口编号')) : showAlert('原生服务未就绪'));

    bindSubmit('handoff-form', () => invoke('HANDOFF_CREATE', {session_id: requiredValue('handoff-session', '咨询会话编号'), subject: requiredValue('handoff-reason', '问题说明')}));
    bindSubmit('feedback-form', () => invoke('CONSULTATION_FEEDBACK', {session_id: requiredValue('feedback-session', '会话编号'), rating: Number(byId('feedback-rating').value), comment: byId('feedback-comment').value.trim()}));
    bindClick('consultation-history', () => invoke('CONSULTATION_HISTORY'));
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
