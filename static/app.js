/**
 * AI Story Engine — Frontend Logic
 * SSE streaming, adventure management, story card editor, settings.
 */

// ─── State ─────────────────────────────────────────────────────────
let isStreaming = false;
let editingCardId = null;

// ─── DOM Refs ──────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const storyDisplay = $('#story-display');
const storyEntries = $('#story-entries');
const welcomeScreen = $('#welcome-screen');
const inputArea = $('#input-area');
const playerInput = $('#player-input');
const actionType = $('#action-type');
const btnSubmit = $('#btn-submit');
const streamingIndicator = $('#streaming-indicator');
const adventureTitle = $('#adventure-title');
const connectionStatus = $('#connection-status');

// ─── API Helpers ───────────────────────────────────────────────────
async function api(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(path, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'API Error');
    }
    return res.json();
}

// ─── Connection Check ──────────────────────────────────────────────
async function checkConnection() {
    try {
        const data = await api('GET', '/api/connection');
        if (data.connected) {
            connectionStatus.className = 'status-dot connected';
            connectionStatus.querySelector('.status-text').textContent = data.model || 'Connected';
        } else {
            connectionStatus.className = 'status-dot disconnected';
            connectionStatus.querySelector('.status-text').textContent = 'No LLM — Launch KoboldCPP';
        }
    } catch {
        connectionStatus.className = 'status-dot disconnected';
        connectionStatus.querySelector('.status-text').textContent = 'No LLM — Launch KoboldCPP';
    }
}

// ─── Adventure Management ──────────────────────────────────────────
async function loadAdventureList() {
    try {
        const list = await api('GET', '/api/adventures');
        const container = $('#adventure-list');
        container.innerHTML = '';
        list.forEach(adv => {
            const el = document.createElement('div');
            el.className = 'adventure-item';
            el.dataset.id = adv.id;
            const date = new Date(adv.updated_at * 1000).toLocaleDateString();
            el.innerHTML = `
                <div class="adventure-item-info">
                    <div class="adventure-item-name">${esc(adv.name)}</div>
                    <div class="adventure-item-meta">${adv.turns} turns · ${date}</div>
                </div>
                <button class="adventure-delete-btn" title="Delete Adventure" data-id="${esc(adv.id)}" data-name="${esc(adv.name)}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            `;
            // Click to load (but not on delete button)
            el.onclick = (e) => {
                if (e.target.closest('.adventure-delete-btn')) return;
                loadAdventure(adv.id);
            };
            // Delete button
            el.querySelector('.adventure-delete-btn').onclick = (e) => {
                e.stopPropagation();
                confirmDeleteAdventure(adv.id, adv.name);
            };
            container.appendChild(el);
        });
    } catch (e) { console.error('Failed to load adventures:', e); }
}

async function confirmDeleteAdventure(id, name) {
    if (!confirm(`Delete adventure "${name}"? This cannot be undone.`)) return;
    try {
        await api('DELETE', `/api/adventure/${id}`);
        showToast('Adventure deleted');
        await loadAdventureList();
        // If we deleted the active one, show welcome screen
        try {
            await api('GET', '/api/adventure');
        } catch {
            adventureTitle.textContent = 'AI Story Engine';
            welcomeScreen.classList.remove('hidden');
            storyDisplay.classList.add('hidden');
            inputArea.classList.add('hidden');
        }
    } catch (e) { showToast('Failed to delete: ' + e.message); }
}

async function loadAdventure(id) {
    try {
        await api('POST', '/api/adventure/load', { id });
        const state = await api('GET', '/api/adventure');
        applyAdventureState(state);
    } catch (e) { showToast('Failed to load: ' + e.message); }
}

async function createAdventure(name) {
    try {
        await api('POST', '/api/adventure/new', { name });
        const state = await api('GET', '/api/adventure');
        applyAdventureState(state);
        await loadAdventureList();
    } catch (e) { showToast('Failed to create: ' + e.message); }
}

function applyAdventureState(state) {
    adventureTitle.textContent = state.name;
    welcomeScreen.classList.add('hidden');
    storyDisplay.classList.remove('hidden');
    inputArea.classList.remove('hidden');

    // Populate editors
    $('#instructions-input').value = state.instructions || '';
    $('#plot-essentials-input').value = state.plot_essentials || '';
    $('#author-note-input').value = state.author_note || '';
    updateTokenBadge('instruct-tokens', state.instructions);
    updateTokenBadge('plot-tokens', state.plot_essentials);
    updateTokenBadge('author-tokens', state.author_note);

    // Render history
    renderHistory(state.history);

    // Story cards
    renderCardsList(state.story_cards);
    $('#cards-count').textContent = state.story_cards?.length || 0;

    // Memory info
    $('#summary-tokens').textContent = (state.summary?.length || 0) + ' chars';
    $('#memory-count').textContent = state.memory_count || 0;
    $('#turn-count').textContent = state.turn_count || 0;
    $('#summary-text').textContent = state.summary || 'No summary yet.';

    // Settings
    if (state.sampling) {
        $('#setting-temperature').value = state.sampling.temperature ?? 0.95;
        $('#setting-min-p').value = state.sampling.min_p ?? 0.05;
        $('#setting-rep-penalty').value = state.sampling.repetition_penalty ?? 1.1;
        $('#setting-max-tokens').value = state.sampling.max_tokens ?? 800;
    }
    $('#setting-context-size').value = state.context_size || 8192;

    // Auto-Cards toggle
    $('#auto-cards-enabled').checked = state.auto_cards_enabled !== false;

    // Inner-Self toggle & brains
    $('#inner-self-enabled').checked = state.inner_self_enabled !== false;
    renderNPCBrains(state.npc_brains || []);
    $('#brains-count').textContent = state.npc_brains?.length || 0;

    // Mark active in list
    $$('.adventure-item').forEach(el => el.classList.toggle('active', el.dataset.id === state.id));
    scrollToBottom();
}

function renderHistory(history) {
    storyEntries.innerHTML = '';
    if (!history) return;
    history.forEach((entry, idx) => {
        const el = createEntryElement(entry, idx, history.length);
        storyEntries.appendChild(el);
    });
}

let activeToolbarIndex = null;

function createEntryElement(entry, idx, totalEntries) {
    const el = document.createElement('div');
    el.className = `story-entry ${entry.role === 'player' ? 'player' : 'narrator'}`;
    el.dataset.index = idx;

    const textEl = document.createElement('span');
    textEl.className = 'entry-text';
    textEl.textContent = entry.text;
    el.appendChild(textEl);

    // Click to toggle toolbar
    el.onclick = (e) => {
        if (e.target.closest('.entry-toolbar') || e.target.closest('.entry-edit-area')) return;
        toggleEntryToolbar(el, idx, totalEntries);
    };

    return el;
}

function toggleEntryToolbar(el, idx, totalEntries) {
    // Close any existing toolbar
    const existing = storyEntries.querySelector('.entry-toolbar');
    if (existing) {
        const wasThisOne = existing.parentElement === el;
        existing.remove();
        activeToolbarIndex = null;
        if (wasThisOne) return; // Toggle off
    }

    activeToolbarIndex = idx;
    const toolbar = document.createElement('div');
    toolbar.className = 'entry-toolbar';

    // Edit button
    const editBtn = document.createElement('button');
    editBtn.className = 'entry-toolbar-btn';
    editBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg> Edit`;
    editBtn.onclick = (e) => { e.stopPropagation(); startEditEntry(el, idx); };
    toolbar.appendChild(editBtn);

    // Rewind button (removes everything after this entry)
    if (idx < totalEntries - 1) {
        const rewindBtn = document.createElement('button');
        rewindBtn.className = 'entry-toolbar-btn danger';
        rewindBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> Rewind Here`;
        rewindBtn.onclick = (e) => { e.stopPropagation(); rewindToEntry(idx); };
        toolbar.appendChild(rewindBtn);
    }

    // Delete single entry
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'entry-toolbar-btn danger';
    deleteBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> Delete`;
    deleteBtn.onclick = (e) => { e.stopPropagation(); deleteSingleEntry(idx); };
    toolbar.appendChild(deleteBtn);

    el.appendChild(toolbar);
}

function startEditEntry(el, idx) {
    // Remove toolbar
    const toolbar = el.querySelector('.entry-toolbar');
    if (toolbar) toolbar.remove();

    const textEl = el.querySelector('.entry-text');
    const original = textEl.textContent;

    const input = document.createElement('textarea');
    input.className = 'entry-edit-area';
    input.value = original;
    textEl.replaceWith(input);
    input.focus();
    // Move cursor to end
    input.selectionStart = input.selectionEnd = input.value.length;

    // Auto-resize
    input.style.height = 'auto';
    input.style.height = input.scrollHeight + 'px';

    const saveEdit = async () => {
        const newText = input.value.trim();
        if (newText && newText !== original) {
            try { await api('POST', '/api/edit', { index: idx, text: newText }); } catch {}
        }
        const newSpan = document.createElement('span');
        newSpan.className = 'entry-text';
        newSpan.textContent = newText || original;
        input.replaceWith(newSpan);
        activeToolbarIndex = null;
    };

    input.onblur = saveEdit;
    input.onkeydown = (e) => {
        if (e.key === 'Escape') { input.value = original; input.blur(); }
        // Allow Enter for newlines, Ctrl+Enter to save
        if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); input.blur(); }
    };
    input.oninput = () => {
        input.style.height = 'auto';
        input.style.height = input.scrollHeight + 'px';
    };

    // Stop click from toggling toolbar
    el.onclick = null;
}

async function rewindToEntry(idx) {
    if (!confirm(`Rewind story to this point? Everything after will be deleted.`)) return;
    try {
        await api('POST', '/api/rewind', { index: idx });
        const state = await api('GET', '/api/adventure');
        renderHistory(state.history);
        scrollToBottom();
        showToast('Rewound to entry');
    } catch (e) { showToast(e.message); }
}

async function deleteSingleEntry(idx) {
    try {
        await api('POST', '/api/delete-entry', { index: idx });
        const state = await api('GET', '/api/adventure');
        renderHistory(state.history);
        scrollToBottom();
    } catch (e) { showToast(e.message); }
}

// Close toolbar on outside click
document.addEventListener('click', (e) => {
    if (!e.target.closest('.story-entry') && activeToolbarIndex !== null) {
        const existing = storyEntries?.querySelector('.entry-toolbar');
        if (existing) existing.remove();
        activeToolbarIndex = null;
    }
});

// ─── Buffered Action (no streaming text) ───────────────────────────
async function consumeSSEBuffered(response) {
    /**
     * Reads the full SSE stream but buffers it — returns the complete text
     * instead of displaying token-by-token.
     */
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';
    let error = null;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
                const data = JSON.parse(line.slice(6));
                if (data.token) fullText += data.token;
                if (data.error) error = data.error;
            } catch {}
        }
    }

    return { fullText, error };
}

async function submitAction() {
    const text = playerInput.value.trim();
    if (!text || isStreaming) return;

    isStreaming = true;
    btnSubmit.disabled = true;
    playerInput.value = '';
    autoResizeInput();

    // Show loading indicator
    streamingIndicator.classList.remove('hidden');
    scrollToBottom();

    try {
        const type = actionType.value;
        const response = await fetch('/api/action', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, action_type: type }),
        });

        // Buffer the entire response
        const { error } = await consumeSSEBuffered(response);

        if (error) {
            showToast(`Error: ${error}`);
        }

        // Render the full state from server
        const finalState = await api('GET', '/api/adventure');
        renderHistory(finalState.history);
        refreshMemoryInfo();

    } catch (e) {
        showToast(`Connection error: ${e.message}`);
    }

    streamingIndicator.classList.add('hidden');
    isStreaming = false;
    btnSubmit.disabled = false;
    scrollToBottom();
    playerInput.focus();
}

function addEntryToDisplay(text, role) {
    const el = document.createElement('div');
    el.className = `story-entry ${role}`;
    const textEl = document.createElement('span');
    textEl.className = 'entry-text';
    textEl.textContent = text;
    el.appendChild(textEl);
    storyEntries.appendChild(el);
}

// ─── Undo / Retry / Continue ───────────────────────────────────────
async function undoAction() {
    if (isStreaming) return;
    try {
        const result = await api('POST', '/api/undo');
        renderHistory(result.history);
        scrollToBottom();
    } catch (e) { showToast(e.message); }
}

async function retryAction() {
    if (isStreaming) return;
    isStreaming = true;
    btnSubmit.disabled = true;
    streamingIndicator.classList.remove('hidden');

    try {
        const response = await fetch('/api/retry', { method: 'POST' });
        const { error } = await consumeSSEBuffered(response);
        if (error) showToast(`Error: ${error}`);

        const state = await api('GET', '/api/adventure');
        renderHistory(state.history);
    } catch (e) { showToast(`Error: ${e.message}`); }

    streamingIndicator.classList.add('hidden');
    isStreaming = false;
    btnSubmit.disabled = false;
    scrollToBottom();
}

async function continueAction() {
    if (isStreaming) return;
    isStreaming = true;
    btnSubmit.disabled = true;
    streamingIndicator.classList.remove('hidden');
    scrollToBottom();

    try {
        const response = await fetch('/api/continue', { method: 'POST' });
        const { error } = await consumeSSEBuffered(response);
        if (error) showToast(`Error: ${error}`);

        const state = await api('GET', '/api/adventure');
        renderHistory(state.history);
        refreshMemoryInfo();
    } catch (e) { showToast(`Error: ${e.message}`); }

    streamingIndicator.classList.add('hidden');
    isStreaming = false;
    btnSubmit.disabled = false;
    scrollToBottom();
}

// ─── Story Cards ───────────────────────────────────────────────────
function renderCardsList(cards) {
    const container = $('#story-cards-list');
    container.innerHTML = '';
    if (!cards || cards.length === 0) return;
    cards.forEach(card => {
        const el = document.createElement('div');
        el.className = `card-item${card.enabled ? '' : ' disabled'}`;
        const autoBadge = card.auto_generated ? '<span class="auto-badge" title="Auto-generated">⚡</span>' : '';
        const promoteBtnHtml = card.auto_generated
            ? `<button class="card-promote-btn" data-card-id="${esc(card.id)}" data-card-name="${esc(card.name)}" title="Promote to Inner-Self brain">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a9 9 0 0 0-9 9c0 3.9 2.5 7.1 6 8.3V21h6v-1.7c3.5-1.2 6-4.4 6-8.3a9 9 0 0 0-9-9z"/><path d="M9 21h6"/><path d="M10 22h4"/></svg>
               </button>`
            : '';
        el.innerHTML = `
            <div class="card-item-info">
                <div class="card-item-name">${autoBadge}${esc(card.name)}</div>
                <div class="card-item-keywords">${esc(card.keywords.join(', '))}</div>
            </div>
            <div class="card-item-actions">
                ${promoteBtnHtml}
                <span class="card-item-priority">${card.priority}</span>
            </div>
        `;
        // Promote to brain handler
        const promoteBtn = el.querySelector('.card-promote-btn');
        if (promoteBtn) {
            promoteBtn.onclick = (e) => {
                e.stopPropagation();
                promoteToBrain(card.id, card.name);
            };
        }
        el.onclick = (e) => {
            if (e.target.closest('.card-promote-btn')) return;
            openCardEditor(card);
        };
        container.appendChild(el);
    });
}

async function promoteToBrain(cardId, cardName) {
    try {
        const result = await api('POST', `/api/npc-brains/promote/${cardId}`);
        if (result.already_existed) {
            showToast(`${cardName} already has a brain`);
        } else {
            showToast(`🧠 Brain created for ${cardName}`);
        }
        // Refresh brains panel
        const state = await api('GET', '/api/adventure');
        renderNPCBrains(state.npc_brains || []);
        $('#brains-count').textContent = state.npc_brains?.length || 0;
    } catch (e) { showToast(e.message); }
}

function openCardEditor(card = null) {
    editingCardId = card ? card.id : null;
    $('#card-editor-title').textContent = card ? 'Edit Story Card' : 'New Story Card';
    $('#card-name').value = card ? card.name : '';
    $('#card-keywords').value = card ? card.keywords.join(', ') : '';
    $('#card-entry').value = card ? card.entry : '';
    $('#card-priority').value = card ? card.priority : 5;
    $('#card-regex').checked = card ? card.use_regex : false;
    $('#btn-delete-card').style.display = card ? 'block' : 'none';
    $('#modal-card-editor').classList.remove('hidden');
    $('#card-name').focus();
}

async function saveCard() {
    const data = {
        name: $('#card-name').value.trim(),
        keywords: $('#card-keywords').value.split(',').map(k => k.trim()).filter(Boolean),
        entry: $('#card-entry').value.trim(),
        priority: parseInt($('#card-priority').value) || 5,
        use_regex: $('#card-regex').checked,
        enabled: true,
    };
    if (!data.name || !data.keywords.length || !data.entry) { showToast('Fill in all fields'); return; }

    try {
        if (editingCardId) {
            await api('PUT', `/api/story-cards/${editingCardId}`, data);
        } else {
            await api('POST', '/api/story-cards', data);
        }
        closeModal('modal-card-editor');
        const state = await api('GET', '/api/adventure');
        renderCardsList(state.story_cards);
        $('#cards-count').textContent = state.story_cards?.length || 0;
    } catch (e) { showToast(e.message); }
}

async function deleteCard() {
    if (!editingCardId) return;
    try {
        await api('DELETE', `/api/story-cards/${editingCardId}`);
        closeModal('modal-card-editor');
        const state = await api('GET', '/api/adventure');
        renderCardsList(state.story_cards);
        $('#cards-count').textContent = state.story_cards?.length || 0;
    } catch (e) { showToast(e.message); }
}

// ─── NPC Brains ────────────────────────────────────────────────────
function renderNPCBrains(brains) {
    const container = $('#npc-brains-list');
    container.innerHTML = '';
    if (!brains || brains.length === 0) return;
    brains.forEach(brain => {
        const el = document.createElement('div');
        el.className = `brain-item${brain.enabled ? '' : ' disabled'}`;
        const thoughtCount = Object.keys(brain.thoughts || {}).length;
        const autoBadge = brain.auto_registered ? '<span class="auto-badge" title="Auto-detected">⚡</span>' : '';
        el.innerHTML = `
            <div class="brain-item-header">
                <div class="brain-item-name">${autoBadge}${esc(brain.name)}</div>
                <div class="brain-item-actions">
                    <span class="brain-thought-count" title="Thoughts">${thoughtCount}</span>
                    <button class="brain-delete-btn" data-name="${esc(brain.name)}" title="Remove">&times;</button>
                </div>
            </div>
        `;
        // Expand thoughts on click
        const header = el.querySelector('.brain-item-header');
        header.onclick = (e) => {
            if (e.target.closest('.brain-delete-btn')) return;
            toggleBrainThoughts(el, brain);
        };
        // Delete
        el.querySelector('.brain-delete-btn').onclick = async (e) => {
            e.stopPropagation();
            try {
                await api('DELETE', `/api/npc-brains/${encodeURIComponent(brain.name)}`);
                const state = await api('GET', '/api/adventure');
                renderNPCBrains(state.npc_brains || []);
                $('#brains-count').textContent = state.npc_brains?.length || 0;
            } catch (err) { showToast(err.message); }
        };
        container.appendChild(el);
    });
}

function toggleBrainThoughts(el, brain) {
    const existing = el.querySelector('.brain-thoughts');
    if (existing) { existing.remove(); return; }

    const thoughts = brain.thoughts || {};
    const entries = Object.entries(thoughts);
    if (entries.length === 0) return;

    const div = document.createElement('div');
    div.className = 'brain-thoughts';
    entries.forEach(([key, val]) => {
        const label = key.replace(/_/g, ' ');
        div.innerHTML += `<div class="brain-thought"><span class="brain-thought-key">${esc(label)}:</span> ${esc(val)}</div>`;
    });
    el.appendChild(div);
}

async function addNPCBrain() {
    const input = $('#npc-name-input');
    const name = input.value.trim();
    if (!name) return;
    input.value = '';
    try {
        await api('POST', '/api/npc-brains', { name });
        const state = await api('GET', '/api/adventure');
        renderNPCBrains(state.npc_brains || []);
        $('#brains-count').textContent = state.npc_brains?.length || 0;
        showToast(`Brain created for ${name}`);
    } catch (e) { showToast(e.message); }
}

// ─── Context Debug ─────────────────────────────────────────────────
async function showContextDebug() {
    const container = $('#context-debug-content');
    container.innerHTML = '<p class="muted">Loading...</p>';
    $('#modal-context').classList.remove('hidden');
    try {
        const data = await api('GET', '/api/context-debug');
        let html = `<div style="margin-bottom:12px;font-size:0.75rem;color:var(--text-muted)">Total: ${data.total_tokens} tokens · Max: ${data.max_context} · Messages: ${data.message_count}</div>`;
        data.messages.forEach(msg => {
            html += `<div class="context-msg ${msg.role}"><div class="context-msg-role">${msg.role}</div><div class="context-msg-text">${esc(msg.content)}</div></div>`;
        });
        container.innerHTML = html;
    } catch (e) { container.innerHTML = `<p class="muted">Error: ${e.message}</p>`; }
}

// ─── Settings ──────────────────────────────────────────────────────
async function saveSettings() {
    const data = {
        llm_endpoint: $('#setting-endpoint').value.trim() || null,
        context_size: parseInt($('#setting-context-size').value) || null,
        temperature: parseFloat($('#setting-temperature').value) || null,
        min_p: parseFloat($('#setting-min-p').value) ?? null,
        repetition_penalty: parseFloat($('#setting-rep-penalty').value) || null,
        max_tokens: parseInt($('#setting-max-tokens').value) || null,
    };
    try {
        await api('PUT', '/api/settings', data);
        closeModal('modal-settings');
        showToast('Settings saved');
        checkConnection();
    } catch (e) { showToast(e.message); }
}

// ─── Sidebar Saves ─────────────────────────────────────────────────
async function savePlotEssentials() {
    const text = $('#plot-essentials-input').value;
    try {
        const r = await api('PUT', '/api/plot-essentials', { text });
        updateTokenBadge('plot-tokens', text);
        showToast('Saved');
    } catch (e) { showToast(e.message); }
}

async function saveAuthorNote() {
    const text = $('#author-note-input').value;
    try {
        await api('PUT', '/api/author-note', { text });
        updateTokenBadge('author-tokens', text);
        showToast('Saved');
    } catch (e) { showToast(e.message); }
}

async function saveInstructions() {
    const text = $('#instructions-input').value;
    try {
        await api('PUT', '/api/instructions', { text });
        updateTokenBadge('instruct-tokens', text);
        showToast('Saved');
    } catch (e) { showToast(e.message); }
}

// ─── Helpers ───────────────────────────────────────────────────────
function esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

function scrollToBottom() {
    storyDisplay.scrollTop = storyDisplay.scrollHeight;
}

function updateTokenBadge(id, text) {
    // Rough token estimate: ~4 chars per token
    const tokens = Math.ceil((text || '').length / 4);
    const el = $(`#${id}`);
    if (el) el.textContent = tokens;
}

function closeModal(id) {
    $(`#${id}`).classList.add('hidden');
}

function autoResizeInput() {
    playerInput.style.height = 'auto';
    playerInput.style.height = Math.min(playerInput.scrollHeight, 120) + 'px';
}

async function refreshMemoryInfo() {
    try {
        const state = await api('GET', '/api/adventure');
        $('#summary-tokens').textContent = (state.summary?.length || 0) + ' chars';
        $('#memory-count').textContent = state.memory_count || 0;
        $('#turn-count').textContent = state.turn_count || 0;
        $('#summary-text').textContent = state.summary || 'No summary yet.';
    } catch {}
}

let toastTimeout;
function showToast(msg) {
    let toast = $('#toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--bg-elevated);color:var(--text-primary);padding:10px 18px;border-radius:var(--radius);border:1px solid var(--border);font-size:0.82rem;z-index:300;box-shadow:var(--shadow);transition:opacity 0.3s;';
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.opacity = '1';
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => { toast.style.opacity = '0'; }, 3000);
}

// ─── Event Listeners ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Sidebar toggle
    $('#btn-sidebar-toggle').onclick = () => {
        $('#sidebar').classList.toggle('open');
        $('#sidebar').classList.toggle('closed');
    };

    // Sidebar section toggles
    $$('.sidebar-section-header').forEach(header => {
        header.onclick = () => {
            const section = header.dataset.section;
            const body = $(`#section-${section}`);
            if (body) {
                body.classList.toggle('collapsed');
                header.classList.toggle('collapsed');
            }
        };
    });

    // Input handling
    playerInput.oninput = autoResizeInput;
    playerInput.onkeydown = (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitAction(); }
    };
    btnSubmit.onclick = submitAction;
    $('#btn-undo').onclick = undoAction;
    $('#btn-retry').onclick = retryAction;
    $('#btn-continue').onclick = continueAction;

    // Action type placeholder
    actionType.onchange = () => {
        const placeholders = { do: 'What do you do?', say: 'What do you say?', story: 'Narrate what happens...' };
        playerInput.placeholder = placeholders[actionType.value] || 'What do you do?';
    };

    // Keyboard shortcuts
    document.onkeydown = (e) => {
        if (e.ctrlKey && e.key === 'z' && !isStreaming) { e.preventDefault(); undoAction(); }
    };

    // New Adventure
    const showNewAdventure = () => {
        $('#modal-new-adventure').classList.remove('hidden');
        $('#new-adventure-name').value = '';
        $('#new-adventure-name').focus();
    };
    $('#btn-new-adventure').onclick = showNewAdventure;
    $('#btn-welcome-new').onclick = showNewAdventure;
    $('#btn-cancel-new').onclick = () => closeModal('modal-new-adventure');
    $('#btn-confirm-new').onclick = () => {
        const name = $('#new-adventure-name').value.trim();
        if (name) { createAdventure(name); closeModal('modal-new-adventure'); }
    };
    $('#new-adventure-name').onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); $('#btn-confirm-new').click(); }
    };

    // Story Cards
    $('#btn-new-card').onclick = () => openCardEditor();
    $('#btn-save-card').onclick = saveCard;
    $('#btn-delete-card').onclick = deleteCard;
    $('#btn-cancel-card').onclick = () => closeModal('modal-card-editor');

    // Sidebar saves
    $('#btn-save-plot').onclick = savePlotEssentials;
    $('#btn-save-author').onclick = saveAuthorNote;
    $('#btn-save-instruct').onclick = saveInstructions;

    // Settings
    $('#btn-settings').onclick = () => {
        // Pre-fill endpoint from current config
        if (!$('#setting-endpoint').value) {
            $('#setting-endpoint').value = 'http://localhost:5001/v1';
        }
        $('#modal-settings').classList.remove('hidden');
    };
    $('#btn-cancel-settings').onclick = () => closeModal('modal-settings');
    $('#btn-save-settings').onclick = saveSettings;

    // Context debug
    $('#btn-context-debug').onclick = showContextDebug;
    $('#btn-close-context').onclick = () => closeModal('modal-context');

    // Close modals on backdrop click
    $$('.modal-backdrop').forEach(backdrop => {
        backdrop.onclick = () => backdrop.parentElement.classList.add('hidden');
    });

    // Auto-Cards toggle
    $('#auto-cards-enabled').onchange = async (e) => {
        try {
            await api('PUT', '/api/auto-cards/toggle', { enabled: e.target.checked });
            showToast(e.target.checked ? 'Auto-Cards enabled' : 'Auto-Cards disabled');
        } catch (err) { showToast(err.message); }
    };

    // Inner-Self toggle
    $('#inner-self-enabled').onchange = async (e) => {
        try {
            await api('PUT', '/api/inner-self/toggle', { enabled: e.target.checked });
            showToast(e.target.checked ? 'Inner-Self enabled' : 'Inner-Self disabled');
        } catch (err) { showToast(err.message); }
    };

    // NPC brain registration
    $('#btn-add-npc').onclick = addNPCBrain;
    $('#npc-name-input').onkeydown = (e) => {
        if (e.key === 'Enter') { e.preventDefault(); addNPCBrain(); }
    };

    // Initial load
    loadAdventureList();
    checkConnection();
    setInterval(checkConnection, 15000);
});
