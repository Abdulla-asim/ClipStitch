/**
 * ClipStory — Dashboard JavaScript
 * Handles all UI interactions: session list, clips, selection,
 * LLM generation, export, settings, and status polling.
 */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────────

let state = {
  sessions:        [],
  currentSessionId: null,
  clips:           [],
  selectedIds:     new Set(),
  lastClipId:      null,   // For shift-click range selection
  currentOutput:   null,   // { output_id, mode, content }
  outputs:         [],     // Previous outputs for history chips
  statusInterval:  null,
};

// ── Init ───────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadSessions();
  loadStatus();
  state.statusInterval = setInterval(loadStatus, 5000);
  // Auto-refresh clips for the active session every 8 s
  setInterval(refreshClipsIfActive, 8000);
});

// ── View switching ─────────────────────────────────────────────────────────────

function showView(name) {
  document.getElementById('viewDashboard').style.display = name === 'dashboard' ? '' : 'none';
  document.getElementById('viewSettings').style.display  = name === 'settings'  ? '' : 'none';
  document.querySelectorAll('.nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.view === name);
  });
  if (name === 'settings') loadSettings();
}

// ── Status polling ─────────────────────────────────────────────────────────────

async function loadStatus() {
  try {
    const s = await api('/api/status');
    const dot  = document.querySelector('#statusBadge .status-dot');
    const text = document.querySelector('#statusBadge .status-text');
    if (s.running) {
      dot.classList.add('active');
      text.textContent = `Monitoring · ${s.current_session_clips} clips`;
    } else {
      dot.classList.remove('active');
      text.textContent = 'Monitor stopped';
    }
  } catch (_) {}
}

// ── Sessions ───────────────────────────────────────────────────────────────────

async function loadSessions() {
  try {
    state.sessions = await api('/api/sessions');
    renderSessions();
    // Auto-select first session (or active one)
    if (state.sessions.length && !state.currentSessionId) {
      selectSession(state.sessions[0].id);
    }
  } catch (e) {
    document.getElementById('sessionList').innerHTML =
      `<div class="empty-state">Failed to load sessions</div>`;
  }
}

function renderSessions() {
  const el = document.getElementById('sessionList');
  if (!state.sessions.length) {
    el.innerHTML = `<div class="empty-state">No sessions yet.<br>Start copying things!</div>`;
    return;
  }
  el.innerHTML = state.sessions.map(s => {
    const date  = fmtDate(s.started_at);
    const dur   = fmtDuration(s.duration_mins);
    const dot   = s.is_active ? `<span class="session-active-dot"></span>` : '';
    const active = s.id === state.currentSessionId ? ' active' : '';
    return `<div class="session-item${active}" id="sess-${s.id}" onclick="selectSession(${s.id})">
      <div class="session-date">${dot}${date}</div>
      <div class="session-meta">
        <span>${s.clip_count} clips</span>
        <span>${dur}</span>
        ${s.is_active ? '<span style="color:var(--emerald)">● Live</span>' : ''}
      </div>
    </div>`;
  }).join('');
}

async function selectSession(id) {
  state.currentSessionId = id;
  state.selectedIds.clear();
  state.currentOutput = null;

  // Update active class
  document.querySelectorAll('.session-item').forEach(el => {
    el.classList.toggle('active', el.id === `sess-${id}`);
  });

  // Reset output panel
  document.getElementById('outputBody').innerHTML =
    `<div class="empty-state output-empty">
       <div class="empty-icon">✦</div>
       <p>Choose a mode and click <b>Generate</b></p>
     </div>`;
  document.getElementById('exportBar').style.display = 'none';
  document.getElementById('outputHistory').innerHTML = '';
  state.outputs = [];

  await loadClips(id);
  await loadOutputHistory(id);
}

// ── Clips ──────────────────────────────────────────────────────────────────────

async function loadClips(sessionId) {
  try {
    state.clips = await api(`/api/sessions/${sessionId}/clips`);
    renderClips();
    updateSelectionInfo();
  } catch (e) {
    document.getElementById('clipsList').innerHTML =
      `<div class="empty-state">Failed to load clips</div>`;
  }
}

async function refreshClipsIfActive() {
  if (!state.currentSessionId) return;
  const sess = state.sessions.find(s => s.id === state.currentSessionId);
  if (!sess || !sess.is_active) return;
  // Reload without wiping selection
  try {
    const fresh = await api(`/api/sessions/${state.currentSessionId}/clips`);
    const added = fresh.filter(c => !state.clips.find(o => o.id === c.id));
    if (added.length) {
      state.clips = fresh;
      renderClips();       // Re-render (selection preserved via Set)
      updateSelectionInfo();
      await loadSessions(); // Refresh session list clip count
    }
  } catch (_) {}
}

function renderClips() {
  const el = document.getElementById('clipsList');
  const badge = document.getElementById('clipCountBadge');

  if (!state.clips.length) {
    el.innerHTML = `<div class="empty-state">No clips in this session</div>`;
    badge.textContent = '';
    return;
  }

  badge.textContent = state.clips.length;

  el.innerHTML = state.clips.map(c => {
    const checked  = state.selectedIds.has(c.id) ? 'checked' : '';
    const selClass = state.selectedIds.has(c.id) ? ' selected' : '';
    const badge    = typeBadge(c.content_type);
    const time     = fmtTime(c.copied_at);
    const lang     = c.language ? `<span class="clip-lang">${c.language}</span>` : '';
    const redact   = c.is_redacted ? `<span class="clip-redacted">⚠ redacted</span>` : '';
    const title    = c.page_title ? `<div class="clip-title">↗ ${esc(c.page_title)}</div>` : '';
    const content  = clipPreview(c);
    return `<div class="clip-item${selClass}" id="clip-${c.id}" onclick="toggleClip(event, ${c.id})">
      <input class="clip-checkbox" type="checkbox" ${checked}
             id="chk-${c.id}" onclick="event.stopPropagation(); toggleClip(event, ${c.id})">
      <div class="clip-body">
        <div class="clip-top">
          ${badge}
          <span class="clip-time">${time}</span>
          ${lang}${redact}
        </div>
        ${title}
        <div class="clip-content ${c.content_type}-clip">${content}</div>
      </div>
    </div>`;
  }).join('');
}

function clipPreview(c) {
  const raw = (c.content || '').trim();
  const trunc = raw.length > 120 ? raw.slice(0, 120) + '…' : raw;
  return esc(trunc);
}

function typeBadge(t) {
  const map = { text: 'TEXT', url: 'URL', code: 'CODE' };
  return `<span class="clip-badge badge-${t}">${map[t] || t.toUpperCase()}</span>`;
}

// ── Clip Selection ─────────────────────────────────────────────────────────────

function toggleClip(event, id) {
  if (event.shiftKey && state.lastClipId !== null) {
    // Range select
    const ids   = state.clips.map(c => c.id);
    const a     = ids.indexOf(state.lastClipId);
    const b     = ids.indexOf(id);
    const [lo, hi] = a < b ? [a, b] : [b, a];
    for (let i = lo; i <= hi; i++) state.selectedIds.add(ids[i]);
  } else {
    if (state.selectedIds.has(id)) {
      state.selectedIds.delete(id);
    } else {
      state.selectedIds.add(id);
    }
    state.lastClipId = id;
  }
  // Sync checkbox + style
  const itemEl = document.getElementById(`clip-${id}`);
  const chkEl  = document.getElementById(`chk-${id}`);
  if (itemEl) itemEl.classList.toggle('selected', state.selectedIds.has(id));
  if (chkEl)  chkEl.checked = state.selectedIds.has(id);
  // Refresh entire render only for shift-range (to update all checkboxes)
  if (event.shiftKey) renderClips();
  updateSelectionInfo();
}

function selectAll() {
  state.clips.forEach(c => state.selectedIds.add(c.id));
  renderClips();
  updateSelectionInfo();
}

function clearSelection() {
  state.selectedIds.clear();
  renderClips();
  updateSelectionInfo();
}

function updateSelectionInfo() {
  const el  = document.getElementById('selectionInfo');
  const cnt = state.selectedIds.size;
  const tot = state.clips.length;
  el.textContent = cnt ? `${cnt} of ${tot} selected` : '';
}

// ── LLM Generation ─────────────────────────────────────────────────────────────

async function generate() {
  if (!state.currentSessionId) {
    alert('Please select a session first.');
    return;
  }
  const mode    = document.getElementById('modeSelect').value;
  const clipIds = state.selectedIds.size ? [...state.selectedIds] : null;

  showLoading(`Generating ${modeName(mode)}…`);

  try {
    const result = await api(`/api/sessions/${state.currentSessionId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, clip_ids: clipIds }),
    });

    state.currentOutput = result;
    renderOutput(result);

    // Refresh output history
    await loadOutputHistory(state.currentSessionId);

    document.getElementById('exportBar').style.display = '';
  } catch (e) {
    hideLoading();
    showError(e.message || 'Generation failed. Check your API key / settings.');
  } finally {
    hideLoading();
  }
}

function renderOutput(result) {
  const body = document.getElementById('outputBody');
  const html = markdownToHtml(result.content || '');
  body.innerHTML = `
    <div style="margin-bottom:0.75rem">
      <span style="font-size:0.72rem;color:var(--text-muted);text-transform:uppercase;
                   letter-spacing:0.06em;font-weight:600">${esc(result.mode_label || result.mode)}</span>
    </div>
    ${html}`;
  // Syntax highlight any code blocks
  body.querySelectorAll('pre code').forEach(el => {
    if (window.hljs) hljs.highlightElement(el);
  });
}

// ── Output History chips ───────────────────────────────────────────────────────

async function loadOutputHistory(sessionId) {
  try {
    const outputs = await api(`/api/sessions/${sessionId}/outputs`);
    state.outputs  = outputs;
    renderOutputHistory();
  } catch (_) {}
}

function renderOutputHistory() {
  const el = document.getElementById('outputHistory');
  if (!state.outputs.length) { el.innerHTML = ''; return; }
  el.innerHTML = state.outputs.map(o => {
    const active = state.currentOutput && state.currentOutput.output_id === o.id ? ' active' : '';
    const ts = fmtTime(o.created_at);
    return `<span class="history-chip${active}" onclick="loadOutput(${o.id})"
                  title="${esc(o.mode_label || o.mode)} · ${ts}">
              ${esc(o.mode_label || o.mode)} <span style="opacity:0.5">${ts}</span>
            </span>`;
  }).join('');
}

async function loadOutput(outputId) {
  const o = state.outputs.find(x => x.id === outputId);
  if (!o) return;
  state.currentOutput = { output_id: o.id, mode: o.mode, content: o.content };
  renderOutput({ ...o, mode_label: o.mode_label });
  document.getElementById('exportBar').style.display = '';
  renderOutputHistory();
}

// ── Export ─────────────────────────────────────────────────────────────────────

function exportAs(fmt) {
  if (!state.currentSessionId) return;
  const outputId = state.currentOutput?.output_id;
  const qs = outputId ? `?output_id=${outputId}` : '';
  window.location.href = `/api/sessions/${state.currentSessionId}/export/${fmt}${qs}`;
}

// ── Settings ───────────────────────────────────────────────────────────────────

async function loadSettings() {
  try {
    const cfg = await api('/api/settings');
    document.getElementById('cfgProvider').value       = cfg.llm?.provider || 'openai';
    document.getElementById('cfgModel').value          = cfg.llm?.model || '';
    document.getElementById('cfgOllamaHost').value     = cfg.llm?.ollama_host || '';
    document.getElementById('cfgOllamaModel').value    = cfg.llm?.ollama_model || '';
    document.getElementById('cfgSessionGap').value     = cfg.monitor?.session_gap_minutes || 30;
    document.getElementById('cfgDedupWindow').value    = cfg.monitor?.dedup_window || 5;
    document.getElementById('cfgRedactKeys').checked   = !!cfg.privacy?.redact_api_keys;
    document.getElementById('cfgRedactPasswords').checked = !!cfg.privacy?.redact_passwords;
    document.getElementById('cfgRedactEmails').checked = !!cfg.privacy?.redact_emails;
    document.getElementById('cfgPort').value           = cfg.web?.port || 5050;
    document.getElementById('cfgOpenOnStart').checked  = !!cfg.web?.open_on_start;
    onProviderChange();
  } catch (e) {
    console.error('Failed to load settings', e);
  }
}

function onProviderChange() {
  const val = document.getElementById('cfgProvider').value;
  const isOllama = val === 'ollama';
  document.getElementById('rowOllamaHost').style.display  = isOllama ? '' : 'none';
  document.getElementById('rowOllamaModel').style.display = isOllama ? '' : 'none';
  document.getElementById('rowModel').style.display       = isOllama ? 'none' : '';
}

async function saveSettings() {
  const provider = document.getElementById('cfgProvider').value;
  const isOllama = provider === 'ollama';
  const body = {
    llm: {
      provider,
      model:        document.getElementById('cfgModel').value,
      ollama_host:  document.getElementById('cfgOllamaHost').value,
      ollama_model: document.getElementById('cfgOllamaModel').value,
    },
    monitor: {
      session_gap_minutes: parseInt(document.getElementById('cfgSessionGap').value, 10),
      dedup_window:        parseInt(document.getElementById('cfgDedupWindow').value, 10),
    },
    privacy: {
      redact_api_keys:  document.getElementById('cfgRedactKeys').checked,
      redact_passwords: document.getElementById('cfgRedactPasswords').checked,
      redact_emails:    document.getElementById('cfgRedactEmails').checked,
    },
    web: {
      port:          parseInt(document.getElementById('cfgPort').value, 10),
      open_on_start: document.getElementById('cfgOpenOnStart').checked,
    },
  };

  const statusEl = document.getElementById('saveStatus');
  try {
    await api('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    statusEl.textContent = '✓ Saved';
    setTimeout(() => { statusEl.textContent = ''; }, 2500);
  } catch (e) {
    statusEl.style.color = 'var(--red)';
    statusEl.textContent = `✗ ${e.message}`;
    setTimeout(() => { statusEl.textContent = ''; statusEl.style.color = ''; }, 3000);
  }
}

// ── Loading overlay ────────────────────────────────────────────────────────────

function showLoading(msg) {
  const el = document.getElementById('loadingOverlay');
  document.getElementById('loadingMsg').textContent = msg || 'Loading…';
  el.classList.add('visible');
}

function hideLoading() {
  document.getElementById('loadingOverlay').classList.remove('visible');
}

// ── Error toast ────────────────────────────────────────────────────────────────

function showError(msg) {
  // Simple inline error in output body
  const body = document.getElementById('outputBody');
  body.innerHTML = `<div class="empty-state output-empty" style="color:var(--red)">
    <div class="empty-icon">⚠</div>
    <p>${esc(msg)}</p>
  </div>`;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

async function api(url, opts = {}) {
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try { const j = await resp.json(); msg = j.error || msg; } catch (_) {}
    throw new Error(msg);
  }
  return resp.json();
}

function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso.replace('T', ' '));
  const today = new Date();
  const y = d.getFullYear(), m = d.getMonth(), day = d.getDate();
  if (y === today.getFullYear() && m === today.getMonth() && day === today.getDate())
    return `Today, ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  const yest = new Date(today); yest.setDate(today.getDate() - 1);
  if (y === yest.getFullYear() && m === yest.getMonth() && day === yest.getDate())
    return `Yesterday, ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function fmtTime(iso) {
  if (!iso) return '';
  return new Date(iso.replace('T', ' ')).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function fmtDuration(mins) {
  if (!mins && mins !== 0) return '';
  const h = Math.floor(mins / 60), m = mins % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

function modeName(key) {
  const map = {
    story: 'Narrative Story', summary: 'Activity Summary',
    worklog: 'Work Log', digest: 'Research Digest',
    email: 'Email Draft', report: 'PDF Report',
  };
  return map[key] || key;
}

/**
 * Minimal markdown → HTML converter for output panel.
 * Handles: ##/### headings, **bold**, `inline code`,
 * ```code blocks```, bullet lists, numbered lists, --- separators.
 */
function markdownToHtml(md) {
  const lines = md.split('\n');
  let html = '';
  let inList = false;
  let inOl = false;
  let inCodeBlock = false;
  let codeLang = '';
  let codeLines = [];

  const flushList = () => {
    if (inList)  { html += '</ul>'; inList = false; }
    if (inOl)    { html += '</ol>'; inOl = false; }
  };

  for (let line of lines) {
    // Code block start/end
    if (line.startsWith('```')) {
      if (!inCodeBlock) {
        flushList();
        codeLang = line.slice(3).trim();
        codeLines = [];
        inCodeBlock = true;
      } else {
        const langAttr = codeLang ? ` class="language-${esc(codeLang)}"` : '';
        html += `<pre><code${langAttr}>${codeLines.map(esc).join('\n')}</code></pre>`;
        inCodeBlock = false;
        codeLang = '';
        codeLines = [];
      }
      continue;
    }
    if (inCodeBlock) { codeLines.push(line); continue; }

    // Headings
    if (line.startsWith('### ')) {
      flushList();
      html += `<h3>${inlineFormat(line.slice(4))}</h3>`;
      continue;
    }
    if (line.startsWith('## ')) {
      flushList();
      html += `<h2>${inlineFormat(line.slice(3))}</h2>`;
      continue;
    }
    if (line.startsWith('# ')) {
      flushList();
      html += `<h2>${inlineFormat(line.slice(2))}</h2>`;
      continue;
    }

    // HR
    if (/^---+$/.test(line.trim())) {
      flushList();
      html += '<hr>';
      continue;
    }

    // Unordered list
    if (/^[-*+] /.test(line)) {
      if (inOl) { html += '</ol>'; inOl = false; }
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inlineFormat(line.slice(2))}</li>`;
      continue;
    }

    // Ordered list
    const olMatch = line.match(/^\d+\. (.+)/);
    if (olMatch) {
      if (inList) { html += '</ul>'; inList = false; }
      if (!inOl) { html += '<ol>'; inOl = true; }
      html += `<li>${inlineFormat(olMatch[1])}</li>`;
      continue;
    }

    // Empty line
    if (!line.trim()) {
      flushList();
      html += '<p></p>';
      continue;
    }

    // Normal paragraph line
    flushList();
    html += `<p>${inlineFormat(line)}</p>`;
  }
  flushList();
  return html;
}

function inlineFormat(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
