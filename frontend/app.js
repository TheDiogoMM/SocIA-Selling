// SocIA Selling - App Logic
let state = {
    activeProfile: localStorage.getItem('activeProfile') || '',
    profiles: JSON.parse(localStorage.getItem('profiles') || '[]'),
    status: { logged_in: false, automation_running: false, stats: {} },
    currentLeadId: null
};

let socket = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Priority: Event Listeners
    initEventListeners();
    initNavigation();
    updateProfileSelector();
    
    // Secondary: Background Status and WS
    try {
        initMobileMenu();
        if (state.activeProfile) {
            refreshStatus();
            loadSettings();
        }
        initWebSocket();
    } catch (e) {
        console.error("Erro na inicialização secundária:", e);
    }
});

// Navigation
function initNavigation() {
    const navLinks = document.querySelectorAll('.nav-links li');
    const pages = document.querySelectorAll('.page');

    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            const pageId = link.getAttribute('data-page');
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            pages.forEach(p => {
                p.classList.remove('active');
                if (p.id === `page-${pageId}`) p.classList.add('active');
            });
            if (pageId === 'leads') loadLeads();
            if (pageId === 'settings') loadSettings();
        });
    });
}

// Profile Management
function updateProfileSelector() {
    const select = document.getElementById('active-profile-select');
    select.innerHTML = '<option value="">+ Selecionar Perfil</option>';
    state.profiles.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p;
        opt.innerText = `@${p}`;
        if (p === state.activeProfile) opt.selected = true;
        select.appendChild(opt);
    });
}

document.getElementById('active-profile-select').onchange = (e) => {
    if (e.target.value) {
        state.activeProfile = e.target.value;
        localStorage.setItem('activeProfile', state.activeProfile);
        refreshStatus();
        loadLeads();
    } else {
        document.getElementById('login-overlay').classList.remove('hidden');
    }
};

// API
async function apiCall(endpoint, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    try {
        const res = await fetch(`/api/${endpoint}`, opts);
        
        if (!res.ok) {
            const errorText = await res.text();
            let errorData;
            try { errorData = JSON.parse(errorText); } catch(e) {}
            const msg = errorData?.error || errorData?.detail || `Erro HTTP ${res.status}: ${errorText.substring(0, 50)}...`;
            showToast(msg, 'danger');
            return null;
        }

        try {
            return await res.json();
        } catch (e) {
            const text = await res.text();
            showToast(`Erro ao processar resposta: ${text.substring(0, 50)}`, 'danger');
            return null;
        }
    } catch (e) {
        showToast(`Erro de conexão: ${e.message}`, 'danger');
        return null;
    }
}

async function refreshStatus() {
    if (!state.activeProfile) return;
    const res = await apiCall(`status?username=${state.activeProfile}`);
    if (res) {
        state.status = res;
        updateUI();
    }
}

function updateUI() {
    const igDot = document.getElementById('ig-login-dot');
    const igText = document.getElementById('ig-login-text');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');

    if (state.status.logged_in) {
        btnStart.disabled = state.status.automation_running;
        btnStop.disabled = !state.status.automation_running;
    } else {
        btnStart.disabled = true;
        btnStop.disabled = true;
    }

    document.getElementById('stat-total').innerText = state.status.stats?.total || 0;
    document.getElementById('stat-respondeu').innerText = state.status.stats?.respondeu || 0;
    document.getElementById('stat-qualificado').innerText = state.status.stats?.qualificado || 0;

    // Feedback de busca (Polling)
    const searchProgress = document.getElementById('search-progress');
    if (state.status.is_searching) {
        searchProgress.classList.remove('hidden');
        document.getElementById('progress-fill').style.width = '100%'; // Indeterminado
    } else if (socket && socket.readyState === WebSocket.OPEN) {
        // Se o WS estiver on, o evento search_done cuida de esconder
    } else {
        searchProgress.classList.add('hidden');
    }
}

// Event Listeners
function initEventListeners() {
    document.getElementById('btn-open-login').onclick = () => document.getElementById('login-overlay').classList.remove('hidden');
    document.getElementById('btn-close-login').onclick = () => document.getElementById('login-overlay').classList.add('hidden');

    document.getElementById('btn-do-login').onclick = async () => {
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        if (!username || !password) return showToast('Preencha tudo', 'warning');

        showToast('Conectando...', 'process');
        const res = await apiCall('login', 'POST', { username, password });
        if (res && res.ok) {
            if (!state.profiles.includes(username)) {
                state.profiles.push(username);
                localStorage.setItem('profiles', JSON.stringify(state.profiles));
            }
            state.activeProfile = username;
            localStorage.setItem('activeProfile', username);
            document.getElementById('login-overlay').classList.add('hidden');
            updateProfileSelector();
            refreshStatus();
        } else {
            showToast(`Erro: ${res?.error || 'Falha no login'}`, 'danger');
        }
    };

    // Alternar abas de Login
    const tabPass = document.getElementById('tab-login-pass');
    const tabSid = document.getElementById('tab-login-sid');
    const sectionPass = document.getElementById('section-login-pass');
    const sectionSid = document.getElementById('section-login-sid');

    if (tabPass && tabSid) {
        tabPass.onclick = () => {
            tabPass.classList.add('active');
            tabSid.classList.remove('active');
            sectionPass.classList.remove('hidden');
            sectionSid.classList.add('hidden');
        };
        tabSid.onclick = () => {
            tabSid.classList.add('active');
            tabPass.classList.remove('active');
            sectionSid.classList.remove('hidden');
            sectionPass.classList.add('hidden');
        };
    }

    // Login via SessionID
    document.getElementById('btn-do-login-sid').onclick = async () => {
        const username = document.getElementById('login-sid-username').value;
        const sessionid = document.getElementById('login-sid-value').value;
        if (!username || !sessionid) return showToast('Preencha Usuário e SessionID', 'warning');

        showToast('Conectando via SessionID...', 'process');
        const res = await apiCall('login/sessionid', 'POST', { username, sessionid });
        if (res && res.ok) {
            const finalUsername = res.username || username;
            if (!state.profiles.includes(finalUsername)) {
                state.profiles.push(finalUsername);
                localStorage.setItem('profiles', JSON.stringify(state.profiles));
            }
            state.activeProfile = finalUsername;
            localStorage.setItem('activeProfile', finalUsername);
            document.getElementById('login-overlay').classList.add('hidden');
            updateProfileSelector();
            refreshStatus();
            showToast('Conectado via SessionID!');
        } else {
            showToast(`Erro SID: ${res?.error || 'Falha no login'}`, 'danger');
        }
    };

    document.getElementById('btn-search').onclick = async () => {
        console.log("Botão de busca clicado.");
        if (!state.activeProfile) return showToast('Selecione um perfil primeiro', 'warning');
        const type = document.getElementById('search-type').value;
        const query = document.getElementById('search-query').value;
        if (!query) return showToast('Digite o termo de busca', 'warning');

        showToast('Iniciando busca...', 'process');
        document.getElementById('search-progress').classList.remove('hidden');
        document.getElementById('progress-fill').style.width = '30%';
        
        console.log(`Disparando busca: ${type} -> ${query} (Keywords: ${document.getElementById('setting-search-keywords').value})`);
        const res = await apiCall('search', 'POST', { profile: state.activeProfile, type, query, max_results: 15 });
        console.log("Resposta da busca:", res);
        
        if (res && res.ok) {
            if (res.count !== undefined) {
                // Busca síncrona (username) concluída
                showToast(`Busca concluída: ${res.count} leads.`);
                loadLeads();
                document.getElementById('search-progress').classList.add('hidden');
            } else {
                // Busca em segundo plano iniciada (hashtag)
                showToast('Busca em andamento...');
            }
        } else {
            document.getElementById('search-progress').classList.add('hidden');
        }
    };

    document.getElementById('btn-start').onclick = async () => {
        const leads = await apiCall(`leads?profile=${state.activeProfile}&status=descoberto`);
        if (!leads || leads.length === 0) return showToast('Nenhum lead novo', 'warning');
        await apiCall('automation/start', 'POST', { profile: state.activeProfile, lead_ids: leads.map(l => l.id) });
    };

    document.getElementById('btn-stop').onclick = async () => {
        await apiCall('automation/stop', 'POST', { username: state.activeProfile });
    };

    document.getElementById('btn-upload-kb').onclick = async () => {
        const fileInput = document.getElementById('kb-file-input');
        if (!fileInput.files[0] || !state.activeProfile) return showToast('Selecione um arquivo', 'warning');

        showToast('Enviando arquivo...', 'process');
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('profile', state.activeProfile);

        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.ok) {
                showToast(`Arquivo ${data.filename} carregado!`);
                loadPlans(); // Recarrega a lista
            } else showToast(data.error, 'danger');
        } catch (e) { showToast(e.message, 'danger'); }
    };

    document.getElementById('btn-save-settings').onclick = async () => {
        const settings = {
            initial_script: document.getElementById('setting-initial-script').value,
            system_prompt: document.getElementById('setting-system-prompt').value,
            search_keywords: document.getElementById('setting-search-keywords').value
        };
        const res = await apiCall('settings', 'POST', { profile: state.activeProfile, settings });
        if (res && res.ok) showToast('Configurações salvas!');
    };
}

// Leads
async function loadLeads() {
    if (!state.activeProfile) return;
    const filter = document.getElementById('filter-status').value;
    const leads = await apiCall(`leads?profile=${state.activeProfile}${filter ? '&status='+filter : ''}`);
    const body = document.getElementById('leads-body');
    body.innerHTML = '';
    
    leads?.forEach(l => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>@${l.username}</strong></td>
            <td><span class="badge ${l.status}">${l.status}</span></td>
            <td><button class="btn secondary sm" onclick="loadLeadDetails('${l.id}')">Chat</button></td>
        `;
        body.appendChild(tr);
    });
}

async function loadLeadDetails(id) {
    const lead = await apiCall(`leads/${id}`);
    if (!lead) return;
    state.currentLeadId = id;
    document.getElementById('dm-panel').classList.remove('hidden');
    document.getElementById('dm-user-name').innerText = `@${lead.username}`;
    document.getElementById('toggle-ai').checked = lead.ai_mode;

    const container = document.getElementById('dm-messages');
    container.innerHTML = '';
    
    if (lead.conversation_summary) {
        container.innerHTML += `<div class="summary-box"><strong>Resumo:</strong> ${lead.conversation_summary}</div>`;
    }

    lead.raw_messages?.forEach(m => {
        const div = document.createElement('div');
        div.className = `msg ${m.role}`;
        div.innerText = m.text;
        container.appendChild(div);
    });
    container.scrollTop = container.scrollHeight;
}

document.getElementById('btn-send-dm').onclick = async () => {
    const text = document.getElementById('dm-text').value;
    if (!text || !state.currentLeadId) return;
    const res = await apiCall(`leads/${state.currentLeadId}/dm`, 'POST', { 
        lead_id: state.currentLeadId, 
        text, 
        profile: state.activeProfile 
    });
    if (res?.ok) {
        document.getElementById('dm-text').value = '';
        loadLeadDetails(state.currentLeadId);
    }
};

document.getElementById('toggle-ai').onchange = async (e) => {
    await apiCall(`leads/ai-mode`, 'POST', { lead_id: state.currentLeadId, ai_mode: e.target.checked });
};

// WebSocket & Polling
function initWebSocket() {
    try {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
        
        socket.onopen = () => {
            console.log("WebSocket conectado.");
            document.getElementById('connection-status').className = 'dot online';
            document.getElementById('connection-text').innerText = 'Conectado (Live)';
        };

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleSocketMessage(data);
            } catch (e) { console.error("Erro ao processar WS:", e); }
        };

        socket.onerror = () => {
            console.warn("Falha no WebSocket. Ativando polling...");
            startPolling();
        };

        socket.onclose = () => {
            console.warn("WebSocket fechado. Ativando polling...");
            startPolling();
        };
    } catch (e) {
        console.error("Erro ao iniciar WebSocket:", e);
        startPolling();
    }
}

function handleSocketMessage(data) {
    if (data.event === 'search_done' && data.profile === state.activeProfile) {
        showToast(`Busca concluída: ${data.new} novos leads.`);
        loadLeads();
        document.getElementById('search-progress').classList.add('hidden');
    }
    if (data.event === 'dm_sent' || data.event === 'reply_received') {
        if (state.currentLeadId === data.lead_id) loadLeadDetails(data.lead_id);
        refreshStatus();
    }
    if (data.event === 'automation_started' || data.event === 'automation_stopped') {
        if (data.profile === state.activeProfile) refreshStatus();
    }
}

let pollingInterval = null;
function startPolling() {
    if (pollingInterval) return;
    document.getElementById('connection-status').className = 'dot online';
    document.getElementById('connection-text').innerText = 'Conectado (Polling)';
    
    pollingInterval = setInterval(() => {
        if (state.activeProfile) {
            refreshStatus();
            // Se estiver na aba de leads, recarrega a lista também
            const activePage = document.querySelector('.page.active');
            if (activePage && activePage.id === 'page-leads') {
                loadLeads();
                if (state.currentLeadId) loadLeadDetails(state.currentLeadId);
            }
        }
    }, 10000); // 10 segundos
}

// Utils
function showToast(msg, type = 'primary') {
    const t = document.getElementById('toast');
    t.innerText = msg;
    t.className = `toast ${type}`;
    t.classList.remove('hidden');
    setTimeout(() => t.classList.add('hidden'), 4000);
}

function logActivity(msg) {
    const log = document.getElementById('log-container');
    const div = document.createElement('div');
    div.className = 'log-entry process';
    div.innerText = `[${new Date().toLocaleTimeString()}] ${msg}`;
    log.prepend(div);
}

async function loadSettings() {
    if (!state.activeProfile) return;
    const s = await apiCall(`settings?profile=${state.activeProfile}`);
    if (s) {
        document.getElementById('setting-initial-script').value = s.initial_script || '';
        document.getElementById('setting-system-prompt').value = s.system_prompt || '';
        document.getElementById('setting-search-keywords').value = s.search_keywords || '';
    }
    loadPlans();
}

async function loadPlans() {
    if (!state.activeProfile) return;
    const plans = await apiCall(`plans?profile=${state.activeProfile}`);
    const body = document.getElementById('plans-body');
    if (!body) return;
    body.innerHTML = '';

    if (!plans || plans.length === 0) {
        body.innerHTML = '<tr><td colspan="3" style="text-align:center; opacity:0.5">Nenhum plano carregado.</td></tr>';
        return;
    }

    plans.forEach(p => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${p.name}</td>
            <td>${p.is_active ? '<span class="plan-active-badge">ATIVO</span>' : '<span style="opacity:0.5">Inativo</span>'}</td>
            <td>
                ${!p.is_active ? `<button class="btn-sm activate" onclick="activatePlan('${p.id}')">Ativar</button>` : ''}
                <button class="btn-sm delete" onclick="deletePlan('${p.id}')">Excluir</button>
            </td>
        `;
        body.appendChild(tr);
    });
}

window.activatePlan = async (id) => {
    const res = await apiCall(`plans/${id}/activate?profile=${state.activeProfile}`, 'POST');
    if (res?.ok) {
        showToast('Plano ativado!');
        loadPlans();
    }
};

window.deletePlan = async (id) => {
    if (!confirm('Excluir este plano?')) return;
    const res = await apiCall(`plans/${id}`, 'DELETE');
    if (res?.ok) {
        showToast('Plano excluído!');
        loadPlans();
    }
};

function initMobileMenu() {
    const btn = document.getElementById('btn-menu-toggle');
    const sidebar = document.querySelector('.sidebar');
    const overlay = document.getElementById('sidebar-overlay');

    const toggle = () => {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('active');
    };

    btn.onclick = toggle;
    overlay.onclick = toggle;

    // Fecha ao clicar em link (mobile)
    document.querySelectorAll('.nav-links li').forEach(link => {
        link.addEventListener('click', () => {
            if (window.innerWidth <= 992) toggle();
        });
    });
}
