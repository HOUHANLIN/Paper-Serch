let generatedQuery = '';
let runtimeTimer = null;
let runtimeStart = null;

function $(selector) {
  return document.querySelector(selector);
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
  const hint = $('#ai-config-hint');
  if (!hint) return;
  const hints = {
    gemini: '当前使用 Gemini：可选填写下方参数，留空则使用 GEMINI_API_KEY 与默认模型。',
    openai: '当前使用 OpenAI/兼容接口：可填写 Base URL 和模型名。',
    ollama: '当前使用本地 Ollama：确保已启动服务，默认 http://localhost:11434/v1。',
    none: '未启用 AI 总结：仅执行检索与 BibTeX 生成。',
  };
  hint.textContent = hints[value] || '选择 AI 模型后可填写对应参数。';
}

function toggleContactFields() {
  const toggle = $('#toggle-contact');
  const block = $('#contact-fields');
  if (!toggle || !block) return;
  const visible = toggle.checked;
  block.style.display = visible ? 'grid' : 'none';
}

function setRuntime(text, tone = 'idle') {
  const runtime = $('#runtime');
  const state = $('#runtime-state');
  if (runtime) runtime.dataset.tone = tone;
  if (state) state.textContent = text;
}

function formatElapsed(seconds) {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function startTimer() {
  runtimeStart = Date.now();
  const elapsedEl = $('#runtime-elapsed');
  const tick = () => {
    if (!runtimeStart || !elapsedEl) return;
    const seconds = Math.max(0, Math.floor((Date.now() - runtimeStart) / 1000));
    elapsedEl.textContent = formatElapsed(seconds);
  };
  tick();
  if (runtimeTimer) clearInterval(runtimeTimer);
  runtimeTimer = setInterval(tick, 1000);
  setRuntime('运行中...', 'running');
}

function stopTimer(success = true, message = '') {
  if (runtimeTimer) clearInterval(runtimeTimer);
  runtimeTimer = null;
  const elapsedEl = $('#runtime-elapsed');
  if (runtimeStart && elapsedEl) {
    const seconds = Math.max(0, Math.floor((Date.now() - runtimeStart) / 1000));
    elapsedEl.textContent = formatElapsed(seconds);
  }
  runtimeStart = null;
  const prefix = success ? '已完成' : '运行失败';
  setRuntime(`${prefix}${message ? `：${message}` : ''}`, success ? 'success' : 'error');
}

function createStatus(entry) {
  const li = document.createElement('li');
  li.className = 'status-item';
  const icon = document.createElement('span');
  const status = entry.status || 'pending';
  icon.className = `status-icon ${status}`;
  icon.textContent = status === 'success' ? '✓' : status === 'error' ? '!' : '…';
  const textBox = document.createElement('div');
  const strong = document.createElement('strong');
  strong.textContent = entry.step || '';
  const detail = document.createElement('p');
  detail.className = 'muted';
  detail.textContent = entry.detail || '';
  textBox.appendChild(strong);
  textBox.appendChild(detail);
  li.appendChild(icon);
  li.appendChild(textBox);
  return li;
}

function createStatusPlaceholder() {
  const li = document.createElement('li');
  li.className = 'status-item';
  li.id = 'status-placeholder';
  li.innerHTML = `<span class="status-icon pending">…</span><div><strong>等待开始</strong><p class="muted">提交后实时显示检索、AI 与导出进度。</p></div>`;
  return li;
}

function resetStatusList(keepEmpty = false) {
  const list = $('#status-list');
  if (!list) return;
  list.innerHTML = '';
  if (!keepEmpty) {
    list.appendChild(createStatusPlaceholder());
  }
}

function appendStatus(entry) {
  const list = $('#status-list');
  if (!list || !entry) return;
  resetStatusList(true);
  list.appendChild(createStatus(entry));
}

function renderStatusLog(entries) {
  if (!entries || !entries.length) return;
  appendStatus(entries[entries.length - 1]);
}

function renderInitialStatus() {
  const initial = window.initialStatusLog || [];
  if (!initial.length) return;
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

function renderArticles(articles) {
  const container = $('#article-container');
  if (!container) return;
  if (!articles || !articles.length) {
    container.innerHTML = '<div class="muted">提交后将在此展示检索到的文献列表与 AI 总结。</div>';
    return;
  }
  const fragments = articles.map((a) => {
    const title = a.url ? `<a href="${a.url}" target="_blank" rel="noreferrer">${a.title}</a>` : a.title;
    const pmid = a.pmid ? `<span class="badge">PMID: ${a.pmid}</span>` : '';
    const direction = a.direction ? `<span class="badge muted">${a.direction}</span>` : '';
    const abstractBlock = a.abstract ? `<p class="paper-abstract"><span class="label">摘要</span>${a.abstract}</p>` : '';
    const summaryBlock = a.summary_zh ? `<p class="paper-summary"><span class="label">AI 总结</span>${a.summary_zh}</p>` : '';
    const usageBlock = a.usage_zh ? `<p class="paper-summary"><span class="label">应用建议</span>${a.usage_zh}</p>` : '';
    return `
      <article class="paper">
        <header class="paper-head">
          <h3>${title}</h3>
          <div class="meta">${a.authors} · ${a.journal} · ${a.year} ${pmid} ${direction}</div>
        </header>
        ${abstractBlock}${summaryBlock}${usageBlock}
      </article>
    `;
  });
  container.innerHTML = fragments.join('');
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
  list.innerHTML = directions
    .map((item) => {
      const status = item.error
        ? `<div class="direction-status error">${item.error}</div>`
        : item.message
          ? `<div class="direction-status">${item.message}</div>`
          : '';
      const queryBlock = item.query ? `<div class="direction-query"><span>检索式：</span><code>${item.query}</code></div>` : '';
      return `<li><div class="direction-title">${item.direction || '未命名方向'}</div>${status}${queryBlock}</li>`;
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
  resetStatusList();
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
      gemini_temperature: $('#gemini_temperature')?.value || '',
      openai_api_key: $('#openai_api_key')?.value || '',
      openai_base_url: $('#openai_base_url')?.value || '',
      openai_model: $('#openai_model')?.value || '',
      openai_temperature: $('#openai_temperature')?.value || '',
      ollama_api_key: $('#ollama_api_key')?.value || '',
      ollama_base_url: $('#ollama_base_url')?.value || '',
      ollama_model: $('#ollama_model')?.value || '',
      ollama_temperature: $('#ollama_temperature')?.value || '',
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
  renderArticles([]);
  updateBibtex('', 0);
  resetStatusList();
  appendStatus({ step: '自动工作流', status: 'running', detail: '正在拆解方向并执行分方向检索…' });
  startTimer();
  if (button) {
    button.disabled = true;
    button.textContent = '运行中...';
  }
  const body = {
    content: contentInput.value,
    source: $('#source')?.value || '',
    years: $('#years')?.value || '',
    max_results_per_direction: 3,
    direction_ai_provider: $('#ai_provider')?.value || '',
    query_ai_provider: $('#ai_provider')?.value || '',
    summary_ai_provider: $('#ai_provider')?.value || '',
    gemini_api_key: $('#gemini_api_key')?.value || '',
    gemini_model: $('#gemini_model')?.value || '',
    gemini_temperature: $('#gemini_temperature')?.value || '',
    openai_api_key: $('#openai_api_key')?.value || '',
    openai_base_url: $('#openai_base_url')?.value || '',
    openai_model: $('#openai_model')?.value || '',
    openai_temperature: $('#openai_temperature')?.value || '',
    ollama_api_key: $('#ollama_api_key')?.value || '',
    ollama_base_url: $('#ollama_base_url')?.value || '',
    ollama_model: $('#ollama_model')?.value || '',
    ollama_temperature: $('#ollama_temperature')?.value || '',
    email: $('#email')?.value || '',
    api_key: $('#api_key')?.value || '',
    output: $('#output')?.value || '',
  };
  try {
    const resp = await fetch('/api/auto_workflow', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showError(data.error || '自动工作流失败，请检查配置。');
      if (data.status_log) renderStatusLog(data.status_log);
      else appendStatus({ step: '自动工作流', status: 'error', detail: data.error || '自动工作流失败' });
      stopTimer(false, data.error || '自动工作流失败');
      return;
    }
    renderDirections(data.directions || []);
    if (data.status_log) renderStatusLog(data.status_log);
    else appendStatus({ step: '自动工作流', status: 'success', detail: '已完成拆解与检索。' });
    updateBibtex(data.bibtex_text || '', data.count || 0);
    renderArticles(data.articles || []);
    stopTimer(true);
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
  const form = $('#search-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      if (e.submitter && e.submitter.classList.contains('export-btn')) return;
      streamSearch(e);
    });
  }
}

window.addEventListener('DOMContentLoaded', () => {
  applySourceDefaults();
  syncProviderPanels();
  toggleContactFields();
  renderInitialStatus();
  wireEvents();
});
