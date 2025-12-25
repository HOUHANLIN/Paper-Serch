let generatedQuery = '';
let runtimeTimer = null;
let runtimeStart = null;
const BASE_STATUS_STEPS = ['准备检索', '检索中', 'AI 摘要', 'BibTeX 生成'];
const STATUS_STEP_ORDER = [
  '自动工作流',
  '提取方向',
  '并发检索',
  '检索方向',
  '生成检索式',
  '检索重试',
  '准备检索',
  '检索中',
  '检索完成',
  'AI 摘要',
  '总结完成',
  'BibTeX 生成',
  '流程中断',
];
const DYNAMIC_STEP_BASE_RANK = STATUS_STEP_ORDER.length + 100;
const dynamicStepRanks = new Map();
let dynamicRankCounter = 0;
const TOOLBAR_SETTINGS_KEY = 'ps-toolbar-settings-v1';
const TOOLBAR_FIELDS = [
  { id: 'ai_provider', mode: 'value' },
  { id: 'source', mode: 'value' },
  { id: 'years', mode: 'value' },
  { id: 'max_results', mode: 'value' },
  { id: 'direction_count', mode: 'value' },
  { id: 'toggle-contact', mode: 'checked' },
  { id: 'email', mode: 'value' },
  { id: 'api_key', mode: 'value' },
  { id: 'openai_api_key', mode: 'value' },
  { id: 'openai_base_url', mode: 'value' },
  { id: 'openai_model', mode: 'value' },
  { id: 'gemini_api_key', mode: 'value' },
  { id: 'gemini_model', mode: 'value' },
  { id: 'ollama_api_key', mode: 'value' },
  { id: 'ollama_base_url', mode: 'value' },
  { id: 'ollama_model', mode: 'value' },
];

function $(selector) {
  return document.querySelector(selector);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

function initTheme() {
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const applyPreferred = () => {
    const saved = localStorage.getItem('ps-theme');
    applyTheme(saved || (media.matches ? 'dark' : 'light'));
  };
  applyPreferred();
  media.addEventListener('change', (evt) => {
    if (localStorage.getItem('ps-theme')) return;
    applyTheme(evt.matches ? 'dark' : 'light');
  });
}

function showError(message) {
  const box = $('#error-box');
  if (!box) return;
  if (message) {
    box.textContent = message;
    box.style.display = 'block';
  } else {
    box.textContent = '';
    box.style.display = 'none';
  }
}

function copyBibtex() {
  const output = $('#bibtex-output');
  const btn = $('#copy-btn');
  if (!output || !output.value.trim()) return;
  const text = output.value;
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      if (btn) {
        const original = btn.textContent;
        btn.textContent = '已复制';
        setTimeout(() => (btn.textContent = original), 1500);
      }
    });
  } else {
    output.select();
    document.execCommand('copy');
  }
}

function applySourceDefaults() {
  const select = $('#source');
  if (!select) return;
  const defaults = (window.sourceDefaults && window.sourceDefaults[select.value]) || {};
  const years = $('#years');
  const max = $('#max_results');
  const email = $('#email');
  const apiKey = $('#api_key');
  const output = $('#output');
  if (years) years.placeholder = defaults.years ? `默认 ${defaults.years}` : '';
  if (max) max.placeholder = defaults.max_results ? `默认 ${defaults.max_results}` : '';
  if (email) email.placeholder = defaults.email ? `默认 ${defaults.email}` : '用于 NCBI 合规';
  if (apiKey) apiKey.placeholder = defaults.api_key ? `默认 ${defaults.api_key}` : '可选 API Key';
  if (output) output.placeholder = defaults.output ? `默认 ${defaults.output}` : '默认使用数据源建议';
}

function syncProviderPanels() {
  const value = $('#ai_provider')?.value || '';
  document.querySelectorAll('.provider-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.provider === value);
  });
}

function toggleContactFields() {
  const toggle = $('#toggle-contact');
  const block = $('#contact-fields');
  if (!toggle || !block) return;
  const visible = toggle.checked;
  block.style.display = visible ? 'grid' : 'none';
}

function setRuntime(text, tone = 'idle') {
  const heroStatusCard = $('#hero-status-card');
  const heroState = $('#hero-state-text');
  const heroIndicator = $('#hero-status-indicator');

  if (heroStatusCard) heroStatusCard.dataset.tone = tone;
  if (heroState) heroState.textContent = text;
  if (heroIndicator) {
    heroIndicator.dataset.running = (tone === 'running');
  }
}

function formatClock(date) {
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const ss = String(date.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

function escapeAttrValue(value) {
  return String(value || '').replace(/"/g, '\\"');
}

function loadToolbarSettings() {
  try {
    const raw = localStorage.getItem(TOOLBAR_SETTINGS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function saveToolbarSettings() {
  try {
    const settings = {};
    TOOLBAR_FIELDS.forEach(({ id, mode }) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (mode === 'checked') settings[id] = Boolean(el.checked);
      else settings[id] = String(el.value ?? '');
    });
    localStorage.setItem(TOOLBAR_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // ignore
  }
}

function restoreToolbarSettings() {
  const settings = loadToolbarSettings();
  TOOLBAR_FIELDS.forEach(({ id, mode }) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (!(id in settings)) return;
    if (mode === 'checked') el.checked = Boolean(settings[id]);
    else el.value = String(settings[id] ?? '');
  });
}

function clearDatalist(datalistId) {
  const dl = document.getElementById(datalistId);
  if (!dl) return;
  dl.innerHTML = '';
}

function fillDatalist(datalistId, models) {
  const dl = document.getElementById(datalistId);
  if (!dl) return;
  dl.innerHTML = '';
  (models || []).forEach((m) => {
    const opt = document.createElement('option');
    opt.value = String(m || '');
    dl.appendChild(opt);
  });
}

async function loadModelsForProvider(event) {
  const btn = event?.currentTarget || null;
  const provider = btn?.dataset?.provider || $('#ai_provider')?.value || '';
  const message = btn?.closest('.model-actions')?.querySelector('.models-message') || null;
  if (!provider) return;
  if (btn) btn.disabled = true;
  if (message) message.textContent = '正在获取模型列表...';

  try {
    const body = {
      provider,
      openai_api_key: $('#openai_api_key')?.value || '',
      openai_base_url: $('#openai_base_url')?.value || '',
      ollama_api_key: $('#ollama_api_key')?.value || '',
      ollama_base_url: $('#ollama_base_url')?.value || '',
      gemini_api_key: $('#gemini_api_key')?.value || '',
    };
    const resp = await fetch('/api/list_models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = data.error || '获取失败，请检查配置或网络';
      if (message) message.textContent = err;
      return;
    }
    const models = data.models || [];
    if (provider === 'openai') fillDatalist('openai-model-options', models);
    if (provider === 'ollama') fillDatalist('ollama-model-options', models);
    if (provider === 'gemini') fillDatalist('gemini-model-options', models);
    if (message) message.textContent = data.message || `已获取 ${models.length} 个模型`;
  } catch (err) {
    console.error(err);
    if (message) message.textContent = '获取失败，请检查配置或网络';
  } finally {
    if (btn) btn.disabled = false;
  }
}

function normalizeStepName(step) {
  return String(step || '').replace(/^\[[^\]]+\]\s*/, '');
}

function getStepRank(step) {
  const full = String(step || '');
  const normalized = normalizeStepName(full);
  const index = STATUS_STEP_ORDER.indexOf(normalized);
  if (index >= 0) return index;
  if (dynamicStepRanks.has(full)) return dynamicStepRanks.get(full);
  const rank = DYNAMIC_STEP_BASE_RANK + dynamicRankCounter;
  dynamicRankCounter += 1;
  dynamicStepRanks.set(full, rank);
  return rank;
}

function insertStatusItemOrdered(list, item) {
  const rank = Number(item.dataset.rank || DYNAMIC_STEP_BASE_RANK);
  const children = Array.from(list.querySelectorAll('.status-item'));
  const before = children.find((child) => Number(child.dataset.rank || DYNAMIC_STEP_BASE_RANK) > rank);
  if (before) list.insertBefore(item, before);
  else list.appendChild(item);
}

function updateProgress() {
  const progressEl = $('#hero-progress-text');
  const list = $('#status-list');
  if (!progressEl || !list) return;
  const total = BASE_STATUS_STEPS.length;
  const done = BASE_STATUS_STEPS.filter((step) => {
    const item = statusState.items.get(step) || list.querySelector(`li[data-step="${escapeAttrValue(step)}"]`);
    return item && item.classList.contains('success');
  }).length;
  progressEl.textContent = `${done}/${total}`;
}

function formatElapsed(seconds) {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function startTimer() {
  runtimeStart = Date.now();
  const heroElapsed = $('#hero-elapsed-text');
  const tick = () => {
    if (!runtimeStart) return;
    const seconds = Math.max(0, Math.floor((Date.now() - runtimeStart) / 1000));
    const formatted = formatElapsed(seconds);
    if (heroElapsed) heroElapsed.textContent = formatted;
  };
  tick();
  if (runtimeTimer) clearInterval(runtimeTimer);
  runtimeTimer = setInterval(tick, 1000);
  setRuntime('运行中...', 'running');
}

function stopTimer(success = true, message = '') {
  if (runtimeTimer) clearInterval(runtimeTimer);
  runtimeTimer = null;
  const heroElapsed = $('#hero-elapsed-text');
  if (runtimeStart) {
    const seconds = Math.max(0, Math.floor((Date.now() - runtimeStart) / 1000));
    const formatted = formatElapsed(seconds);
    if (heroElapsed) heroElapsed.textContent = formatted;
  }
  runtimeStart = null;
  const prefix = success ? '已完成' : '运行失败';
  setRuntime(`${prefix}${message ? `：${message}` : ''}`, success ? 'success' : 'error');
}

function createStatus(entry) {
  const li = document.createElement('li');
  const status = entry.status || 'pending';
  li.className = `status-item ${status}`;
  li.dataset.step = entry.step || '';
  li.dataset.rank = String(getStepRank(entry.step || ''));

  const icon = document.createElement('span');
  icon.className = `status-icon ${status}`;
  icon.textContent = status === 'success' ? '✓' : status === 'error' ? '!' : status === 'running' ? '⏳' : '…';

  const textBox = document.createElement('div');
  const titleRow = document.createElement('div');
  titleRow.className = 'status-title-row';

  const strong = document.createElement('strong');
  strong.textContent = entry.step || '';

  const time = document.createElement('span');
  time.className = 'status-time muted';
  time.textContent = entry.time || formatClock(new Date());

  titleRow.appendChild(strong);
  titleRow.appendChild(time);

  textBox.appendChild(titleRow);
  li.appendChild(icon);
  li.appendChild(textBox);
  return li;
}

function resetStatusList(withInitialSteps = false) {
  const list = $('#status-list');
  if (!list) return;
  list.innerHTML = '';
  statusState.clear();
  if (withInitialSteps) {
    BASE_STATUS_STEPS.forEach(step => {
      const li = createStatus({ step, status: 'pending', detail: '等待执行...' });
      statusState.items.set(step, li);
      list.appendChild(li);
    });
    const first = list.querySelector('.status-item');
    if (first) {
      first.classList.add('active');
      statusState.activeEl = first;
    }
  }
  updateProgress();
}

const statusState = {
  items: new Map(), // step -> <li>
  pending: new Map(), // step -> latest entry
  pendingOrder: [], // steps in arrival order (for active selection)
  flushScheduled: false,
  activeEl: null,
  clear() {
    this.items.clear();
    this.pending.clear();
    this.pendingOrder.length = 0;
    this.flushScheduled = false;
    this.activeEl = null;
  },
};

function _updateStatusItem(item, entry) {
  const status = entry.status || 'pending';
  item.className = `status-item ${status}`;
  item.dataset.rank = String(getStepRank(entry.step || item.dataset.step || ''));
  const icon = item.querySelector('.status-icon');
  if (icon) {
    icon.className = `status-icon ${status}`;
    icon.textContent = status === 'success' ? '✓' : status === 'error' ? '!' : status === 'running' ? '⏳' : '…';
  }
  const time = item.querySelector('.status-time');
  if (time) time.textContent = entry.time || formatClock(new Date());
}

function _insertStatusItem(list, item, step) {
  // Base steps keep their order; dynamic steps append to avoid O(n) reorder thrash under concurrency.
  const normalized = normalizeStepName(step || '');
  const isBase = STATUS_STEP_ORDER.includes(normalized) || BASE_STATUS_STEPS.includes(normalized);
  if (!isBase) {
    list.appendChild(item);
    return;
  }
  insertStatusItemOrdered(list, item);
}

function _flushStatusUpdates() {
  statusState.flushScheduled = false;
  const list = $('#status-list');
  if (!list) return;

  const placeholder = document.getElementById('status-placeholder');
  if (placeholder) placeholder.remove();

  let lastActiveStep = null;
  for (const step of statusState.pendingOrder) {
    const entry = statusState.pending.get(step);
    if (!entry) continue;

    let item = statusState.items.get(step);
    if (!item) {
      item = createStatus(entry);
      statusState.items.set(step, item);
      _insertStatusItem(list, item, step);
    } else {
      _updateStatusItem(item, entry);
    }
    lastActiveStep = step;
  }

  statusState.pending.clear();
  statusState.pendingOrder.length = 0;

  if (lastActiveStep) {
    const activeEl = statusState.items.get(lastActiveStep);
    if (activeEl) {
      if (statusState.activeEl && statusState.activeEl !== activeEl) {
        statusState.activeEl.classList.remove('active');
      }
      activeEl.classList.add('active');
      statusState.activeEl = activeEl;

      const card = $('#hero-status-card');
      const expanded = Boolean(card && card.classList.contains('expanded'));
      if (expanded) {
        const nearBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 40;
        if (nearBottom) list.scrollTop = list.scrollHeight;
      }
    }
  }

  updateProgress();
}

function appendStatus(entry) {
  if (!entry || !entry.step) return;
  const step = String(entry.step || '');
  statusState.pending.set(step, entry);
  statusState.pendingOrder.push(step);

  // Some steps are only emitted as "running" and never explicitly finalized by the backend.
  // Make them "done" once a later terminal step arrives, so the UI doesn't get stuck at ⏳.
  if (step === '检索完成' && (entry.status === 'success' || entry.status === 'error')) {
    statusState.pending.set('检索中', {
      step: '检索中',
      status: entry.status === 'error' ? 'error' : 'success',
      detail: '已结束',
    });
    statusState.pendingOrder.push('检索中');
  }

  if (statusState.flushScheduled) return;
  statusState.flushScheduled = true;
  requestAnimationFrame(_flushStatusUpdates);
}

function ensureAiStatusFinal(payload) {
  const list = $('#status-list');
  if (!list) return;
  const aiStep = 'AI 摘要';
  const item = list.querySelector(`li[data-step="${escapeAttrValue(aiStep)}"]`);
  if (!item) return;
  if (item.classList.contains('success') || item.classList.contains('error')) return;

  const articles = (payload && payload.articles) || [];
  const hasAiContent = Array.isArray(articles) && articles.some((a) => {
    const summary = (a && a.summary_zh) || '';
    const usage = (a && a.usage_zh) || '';
    return String(summary).trim() || String(usage).trim();
  });
  appendStatus({
    step: aiStep,
    status: 'success',
    detail: hasAiContent ? 'AI 摘要已完成' : 'AI 摘要已完成（未生成内容或未启用）',
  });
}

window.toggleStatusModule = function () {
  const card = $('#hero-status-card');
  if (!card) return;
  card.classList.toggle('expanded');
  localStorage.setItem('ps-status-expanded', card.classList.contains('expanded') ? '1' : '0');
};

function renderStatusLog(entries) {
  if (!entries || !entries.length) return;
  resetStatusList(false);
  entries.forEach(entry => appendStatus(entry));
}

function renderInitialStatus() {
  const initial = window.initialStatusLog || [];
  if (!initial.length) {
    resetStatusList(false);
    const placeholder = document.createElement('li');
    placeholder.className = 'status-item active';
    placeholder.innerHTML = `<span class="status-icon pending">…</span><div><div class="status-title-row"><strong>等待开始</strong><span class="status-time muted">${formatClock(new Date())}</span></div></div>`;
    $('#status-list')?.appendChild(placeholder);
    return;
  }
  renderStatusLog(initial);
}

function updateBibtex(bibtexText, count) {
  const output = $('#bibtex-output');
  const hidden = $('#bibtex-hidden');
  const countEl = $('#result-count');
  const copyBtn = $('#copy-btn');
  const exportBtn = document.querySelector('.export-btn');
  if (output) output.value = bibtexText || '';
  if (hidden) hidden.value = bibtexText || '';
  if (countEl) countEl.textContent = `共 ${count || 0} 条记录`;
  const disabled = !bibtexText;
  if (copyBtn) copyBtn.disabled = disabled;
  if (exportBtn) exportBtn.disabled = disabled;
}

function buildArticleMarkup(a, showDirectionBadge = true) {
  const title = a.url ? `<a href="${a.url}" target="_blank" rel="noreferrer">${a.title}</a>` : a.title;
  const pmid = a.pmid ? `<span class="badge">PMID: ${a.pmid}</span>` : '';
  const direction = a.direction && showDirectionBadge ? `<span class="badge muted">${a.direction}</span>` : '';

  return `
    <article class="paper" id="paper-${a.pmid || Math.random().toString(36).substr(2, 9)}">
      <header class="paper-head">
        <h3>${title}</h3>
        <div class="meta">${a.authors} · ${a.journal} · ${a.year} ${pmid} ${direction}</div>
      </header>

      <div class="paper-details visible">
        ${a.summary_zh ? `
          <div class="ai-content-box">
            <div class="card-kicker">✨ 全文概括</div>
            <p class="paper-summary">${a.summary_zh}</p>
          </div>
        ` : ''}
        ${a.usage_zh ? `
          <div class="ai-content-box usage">
            <div class="card-kicker">🎯 引用建议</div>
            <p class="paper-summary">${a.usage_zh}</p>
          </div>
        ` : ''}
        ${!a.summary_zh && !a.usage_zh ? '<p class="muted">暂无 AI 总结</p>' : ''}
      </div>
    </article>
  `;
}

window.togglePaper = function (btn) {
  const paper = btn.closest('.paper');
  const isExpanded = paper.dataset.expanded === 'true';
  paper.dataset.expanded = !isExpanded;
  btn.querySelector('.btn-text').textContent = isExpanded ? '查看摘要与 AI 总结' : '收起详情';
  btn.querySelector('.icon').textContent = isExpanded ? '↓' : '↑';
};

function renderArticles(articles) {
  const container = $('#article-container');
  if (!container) return;
  if (!articles || !articles.length) {
    container.innerHTML = '<div class="muted">提交后将在此展示检索到的文献列表。</div>';
    return;
  }
  const fragments = articles.map((a) => buildArticleMarkup(a));
  container.innerHTML = fragments.join('');
}

function renderDirectionGroups(directionDetails) {
  const container = $('#direction-results');
  if (!container) return;
  if (!directionDetails || !directionDetails.length) {
    container.innerHTML = '<div class="muted">运行后将按检索点分组展示文献。</div>';
    return;
  }
  const blocks = directionDetails.map((detail, idx) => {
    const hasError = Boolean(detail.error);
    const articles = detail.articles || [];
    const heading = detail.direction || `检索点 ${idx + 1}`;
    const state = hasError
      ? `<div class="direction-status error">${detail.error}</div>`
      : `<div class="direction-status">${detail.message || `共 ${articles.length} 条结果`}</div>`;
    const articleCards = articles.length
      ? articles.map((a) => buildArticleMarkup(a, false)).join('')
      : '<div class="muted">暂无检索结果</div>';
    return `
      <section class="direction-group" data-state="${hasError ? 'error' : 'ok'}">
        <header class="direction-group-head">
          <div>
            <div class="direction-tag">检索点</div>
            <h3>${heading}</h3>
          </div>
          <div class="direction-meta">
            ${state}
          </div>
        </header>
        <div class="direction-articles">
          ${articleCards}
        </div>
      </section>
    `;
  });
  container.innerHTML = blocks.join('');
}

function renderDirections(directions) {
  const list = $('#direction-list');
  const message = $('#direction-message');
  if (!list || !message) return;
  if (!directions || !directions.length) {
    message.textContent = '等待输入以自动拆解检索方向。';
    list.innerHTML = '';
    return;
  }
  message.textContent = '已提取到以下检索方向：';
  const hasAiContent = (articles) => {
    if (!Array.isArray(articles)) return false;
    return articles.some((a) => {
      const summary = String((a && a.summary_zh) || '').trim();
      const usage = String((a && a.usage_zh) || '').trim();
      return summary || usage;
    });
  };
  list.innerHTML = directions
    .map((item) => {
      const direction = item.direction || '未命名方向';
      const error = item.error ? `<div class="direction-status error">${item.error}</div>` : '';

      const countVal =
        typeof item.count === 'number' ? item.count : Array.isArray(item.articles) ? item.articles.length : null;
      const countText = countVal == null ? '—' : String(countVal);

      const retryCount = typeof item.retry_count === 'number' ? item.retry_count : null;
      const retryText = retryCount == null ? '—' : String(retryCount);

      const aiOk = hasAiContent(item.articles);
      const aiText = item.error ? '否' : aiOk ? '是' : countVal == null ? '—' : '否';

      const metrics = `
        <div class="direction-metrics">
          <span class="badge muted">结果：${countText}</span>
          <span class="badge muted">AI 总结：${aiText}</span>
          <span class="badge muted">重试：${retryText}</span>
        </div>
      `;

      return `<li><div class="direction-title">${direction}</div>${metrics}${error}</li>`;
    })
    .join('');
}

function parseSse(chunk) {
  const lines = chunk.split('\n');
  let eventType = 'message';
  let dataLine = '';
  lines.forEach((line) => {
    if (line.startsWith('event:')) eventType = line.replace('event:', '').trim();
    else if (line.startsWith('data:')) dataLine += line.replace('data:', '').trim();
  });
  let payload = {};
  try {
    payload = dataLine ? JSON.parse(dataLine) : {};
  } catch (err) {
    console.error('解析事件失败', err, chunk);
  }
  return { eventType, payload };
}

async function streamSearch(event) {
  if (event) event.preventDefault();
  const form = $('#search-form');
  const submit = $('#submit-btn');
  if (!form) return;
  resetStatusList(true); // withInitialSteps
  showError('');
  updateBibtex('', 0);
  renderArticles([]);
  startTimer();
  if (submit) {
    submit.disabled = true;
    submit.textContent = '运行中...';
  }
  const formData = new FormData(form);
  try {
    const resp = await fetch('/api/search_stream', { method: 'POST', body: formData });
    if (!resp.ok || !resp.body) throw new Error('接口返回异常');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      parts.filter(Boolean).forEach((part) => {
        const { eventType, payload } = parseSse(part);
        if (eventType === 'status' && payload.entry) appendStatus(payload.entry);
        if (eventType === 'error' && payload.message) {
          showError(payload.message);
          stopTimer(false, payload.message);
        }
        if (eventType === 'result') {
          ensureAiStatusFinal(payload);
          updateBibtex(payload.bibtex_text, payload.count);
          renderArticles(payload.articles || []);
          stopTimer(true);
        }
      });
    }
    if (buffer.trim()) {
      const { eventType, payload } = parseSse(buffer.trim());
      if (eventType === 'status' && payload.entry) appendStatus(payload.entry);
      if (eventType === 'error' && payload.message) {
        showError(payload.message);
        stopTimer(false, payload.message);
      }
      if (eventType === 'result') {
        ensureAiStatusFinal(payload);
        updateBibtex(payload.bibtex_text, payload.count);
        renderArticles(payload.articles || []);
        stopTimer(true);
      }
    }
  } catch (err) {
    console.error(err);
    showError('检索失败，请检查配置或网络。');
    stopTimer(false, '接口异常或网络问题');
  } finally {
    if (submit) {
      submit.disabled = false;
      submit.textContent = '检索并生成 BibTeX';
    }
    if (runtimeStart) stopTimer(true);
  }
}

async function generateQuery() {
  const intent = $('#intent');
  const message = $('#generator-message');
  const preview = $('#generator-preview');
  const applyActions = $('#generator-actions');
  const button = $('#btn-generate-query');
  if (!intent || !intent.value.trim()) {
    if (message) message.textContent = '请先输入你要检索的自然语言需求。';
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = '生成中...';
  }
  try {
    const body = {
      source: $('#source')?.value || '',
      intent: intent.value,
      ai_provider: $('#ai_provider')?.value || '',
      gemini_api_key: $('#gemini_api_key')?.value || '',
      gemini_model: $('#gemini_model')?.value || '',
      gemini_temperature: 0,
      openai_api_key: $('#openai_api_key')?.value || '',
      openai_base_url: $('#openai_base_url')?.value || '',
      openai_model: $('#openai_model')?.value || '',
      openai_temperature: 0,
      ollama_api_key: $('#ollama_api_key')?.value || '',
      ollama_base_url: $('#ollama_base_url')?.value || '',
      ollama_model: $('#ollama_model')?.value || '',
      ollama_temperature: parseFloat($('#ollama_temperature')?.value || '0'),
    };
    const resp = await fetch('/api/generate_query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    generatedQuery = data.query || '';
    if (preview) {
      preview.textContent = generatedQuery || '未生成检索式，请检查配置。';
    }
    if (applyActions) applyActions.style.opacity = generatedQuery ? '1' : '0.5';
    if (message) message.textContent = data.message || '已生成预览。';
  } catch (err) {
    console.error(err);
    if (message) message.textContent = '生成失败，请稍后重试或检查网络配置。';
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'AI 生成检索式';
    }
  }
}

function applyGeneratedQuery() {
  if (!generatedQuery) return;
  const query = $('#query');
  if (query) {
    query.value = generatedQuery;
    query.focus();
  }
}

async function runAutoWorkflow(event) {
  if (event) event.preventDefault();
  const contentInput = $('#direction-text');
  const button = $('#btn-auto-workflow');
  if (!contentInput || !contentInput.value.trim()) {
    showError('请先提供需要拆解的文本。');
    return;
  }
  showError('');
  renderDirections([]);
  if ($('#direction-results')) {
    renderDirectionGroups([]);
  } else {
    renderArticles([]);
  }
  updateBibtex('', 0);
  resetStatusList(false);
  appendStatus({ step: '自动工作流', status: 'running', detail: '正在拆解内容方向...' });
  startTimer();
  if (button) {
    button.disabled = true;
    button.textContent = '运行中...';
  }
  const body = {
    content: contentInput.value,
    source: $('#source')?.value || '',
    years: $('#years')?.value || '',
    direction_count: parseInt($('#direction_count')?.value || '', 10) || '',
    max_results_per_direction: parseInt($('#max_results')?.value || '3', 10) || 3,
    concurrency: parseInt($('#concurrency')?.value || '3', 10) || 3,
    direction_ai_provider: $('#ai_provider')?.value || '',
    query_ai_provider: $('#ai_provider')?.value || '',
    summary_ai_provider: $('#ai_provider')?.value || '',
    gemini_api_key: $('#gemini_api_key')?.value || '',
    gemini_model: $('#gemini_model')?.value || '',
    gemini_temperature: 0,
    openai_api_key: $('#openai_api_key')?.value || '',
    openai_base_url: $('#openai_base_url')?.value || '',
    openai_model: $('#openai_model')?.value || '',
    openai_temperature: 0,
    ollama_api_key: $('#ollama_api_key')?.value || '',
    ollama_base_url: $('#ollama_base_url')?.value || '',
    ollama_model: $('#ollama_model')?.value || '',
    ollama_temperature: parseFloat($('#ollama_temperature')?.value || '0'),
    email: $('#email')?.value || '',
    api_key: $('#api_key')?.value || '',
    output: $('#output')?.value || '',
  };
  try {
    const resp = await fetch('/api/auto_workflow_stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok || !resp.body) {
      const data = await resp.json().catch(() => ({}));
      showError(data.error || '自动工作流失败，请检查配置。');
      if (data.status_log) renderStatusLog((data.status_log || []).filter((e) => !String(e.step || '').startsWith('[')));
      else appendStatus({ step: '自动工作流', status: 'error', detail: data.error || '自动工作流失败' });
      stopTimer(false, data.error || '自动工作流失败');
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const directionDetails = [];
    let workflowTotal = 0;
    let scheduledDirectionRender = false;
    const combinedBibtexParts = [];
    let combinedCount = 0;
    let combinedArticles = [];
    let workflowFinished = 0;
    let workflowAnyError = false;
    let milestonesEmitted = false;

    const scheduleRenderDirections = () => {
      if (scheduledDirectionRender) return;
      scheduledDirectionRender = true;
      requestAnimationFrame(() => {
        scheduledDirectionRender = false;
        renderDirections(directionDetails);
        if ($('#direction-results')) renderDirectionGroups(directionDetails);
      });
    };

    const maybeEmitMilestones = () => {
      if (milestonesEmitted || !workflowTotal) return;
      if (workflowFinished < workflowTotal) return;
      appendStatus({ step: '检索完成', status: workflowAnyError ? 'error' : 'success' });
      appendStatus({ step: '总结完成', status: workflowAnyError ? 'error' : 'success' });
      milestonesEmitted = true;
    };

    const updateCombined = () => {
      const combinedBibtex = combinedBibtexParts.filter(Boolean).join('\n\n');
      updateBibtex(combinedBibtex, combinedCount);
      if ($('#direction-results')) renderDirectionGroups(directionDetails);
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      parts.filter(Boolean).forEach((part) => {
        const { eventType, payload } = parseSse(part);
        if (eventType === 'status' && payload.entry) {
          const step = String(payload.entry.step || '');
          if (!step.startsWith('[')) appendStatus(payload.entry);
        }
        if (eventType === 'error' && payload.message) {
          showError(payload.message);
          stopTimer(false, payload.message);
          appendStatus({ step: '自动工作流', status: 'error', detail: payload.message });
        }
        if (eventType === 'workflow_init') {
          const dirs = payload.directions || [];
          directionDetails.length = 0;
          workflowTotal = Array.isArray(dirs) ? dirs.length : 0;
          workflowFinished = 0;
          workflowAnyError = false;
          milestonesEmitted = false;
          dirs.forEach((d) => directionDetails.push({ direction: String(d || ''), message: '等待执行...' }));
          scheduleRenderDirections();
        }
        if (eventType === 'direction_result' && payload.detail) {
          const idx = Number(payload.index || 0);
          if (!Number.isNaN(idx) && idx >= 0) directionDetails[idx] = payload.detail;
          workflowFinished += 1;
          if (payload.detail.error) workflowAnyError = true;
          maybeEmitMilestones();
          scheduleRenderDirections();
          if (payload.detail && !payload.detail.error) {
            combinedCount += Number(payload.detail.count || 0);
            if (payload.detail.bibtex_text) combinedBibtexParts.push(String(payload.detail.bibtex_text || '').trim());
            const articles = payload.detail.articles || [];
            if (Array.isArray(articles) && articles.length) combinedArticles = combinedArticles.concat(articles);
            updateCombined();
          }
        }
        if (eventType === 'workflow_done') {
          const dirs = payload.directions || directionDetails;
          maybeEmitMilestones();
          renderDirections(Array.isArray(dirs) ? dirs : directionDetails);
          if ($('#direction-results')) renderDirectionGroups(Array.isArray(dirs) ? dirs : directionDetails);
          updateBibtex(payload.bibtex_text || combinedBibtexParts.join('\n\n'), payload.count || combinedCount);
          ensureAiStatusFinal({ articles: payload.articles || combinedArticles });
          showError('');
          stopTimer(true);
          appendStatus({ step: '自动工作流', status: 'success', detail: '已完成' });
        }
      });
    }

    if (buffer.trim()) {
      const { eventType, payload } = parseSse(buffer.trim());
      if (eventType === 'status' && payload.entry) {
        const step = String(payload.entry.step || '');
        if (!step.startsWith('[')) appendStatus(payload.entry);
      }
      if (eventType === 'error' && payload.message) {
        showError(payload.message);
        stopTimer(false, payload.message);
      }
      if (eventType === 'workflow_done') {
        const dirs = payload.directions || directionDetails;
        renderDirections(Array.isArray(dirs) ? dirs : directionDetails);
        if ($('#direction-results')) renderDirectionGroups(Array.isArray(dirs) ? dirs : directionDetails);
        updateBibtex(payload.bibtex_text || combinedBibtexParts.join('\n\n'), payload.count || combinedCount);
        ensureAiStatusFinal({ articles: payload.articles || combinedArticles });
        showError('');
        stopTimer(true);
        appendStatus({ step: '自动工作流', status: 'success', detail: '已完成' });
      }
    }
  } catch (err) {
    console.error(err);
    showError('自动工作流失败，请检查网络或 AI 配置。');
    stopTimer(false, '接口异常');
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = '一键拆解并检索';
    }
  }
}

function wireEvents() {
  $('#ai_provider')?.addEventListener('change', syncProviderPanels);
  $('#source')?.addEventListener('change', applySourceDefaults);
  $('#toggle-contact')?.addEventListener('change', toggleContactFields);
  $('#btn-generate-query')?.addEventListener('click', generateQuery);
  $('#btn-apply-query')?.addEventListener('click', applyGeneratedQuery);
  $('#btn-auto-workflow')?.addEventListener('click', runAutoWorkflow);
  $('#copy-btn')?.addEventListener('click', copyBibtex);
  document.querySelectorAll('.btn-load-models').forEach((button) => {
    button.addEventListener('click', loadModelsForProvider);
  });

  TOOLBAR_FIELDS.forEach(({ id }) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('change', saveToolbarSettings);
    el.addEventListener('input', saveToolbarSettings);
  });

  const form = $('#search-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      if (e.submitter && e.submitter.classList.contains('export-btn')) return;
      streamSearch(e);
    });
  }
}

window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  const card = $('#hero-status-card');
  if (card) card.classList.toggle('expanded', localStorage.getItem('ps-status-expanded') === '1');
  restoreToolbarSettings();
  applySourceDefaults();
  syncProviderPanels();
  toggleContactFields();
  renderInitialStatus();
  wireEvents();
});
