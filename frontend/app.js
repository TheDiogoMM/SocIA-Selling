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

    document.getElementById('btn-search').onclick = async () => {
        if (!state.activeProfile) return showToast('Selecione um perfil primeiro', 'warning');
        const type = document.getElementById('search-type').value;
        const query = document.getElementById('search-query').value;
        if (!query) return showToast('Digite o termo de busca', 'warning');

        document.getElementById('search-progress').classList.remove('hidden');
        document.getElementById('progress-fill').style.width = '0%';
        await apiCall('search', 'POST', { profile: state.activeProfile, type, query, max_results: 15 });
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

        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        formData.append('profile', state.activeProfile);

        try {
            const res = await fetch('/api/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.ok) showToast(`Arquivo ${data.filename} carregado!`);
            else showToast(data.error, 'danger');
        } catch (e) { showToast(e.message, 'danger'); }
    };

    document.getElementById('btn-save-settings').onclick = async () => {
        const settings = {
            initial_script: document.getElementById('setting-initial-script').value,
            system_prompt: document.getElementById('setting-system-prompt').value
        };
        const res = await apiCall('settings', 'POST', { profile: state.activeProfile, settings });
        if (res && res.ok) showToast('Salvo!');
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

// WebSocket
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
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
    };
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
    }
}
