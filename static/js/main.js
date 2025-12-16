function copyBibtex() {
  const textarea = document.getElementById('bibtex-output');
  const btn = document.getElementById('copy-btn');
  if (!textarea || !textarea.value.trim()) {
    return;
  }
  textarea.select();
  textarea.setSelectionRange(0, 999999);
  try {
    document.execCommand('copy');
    if (btn) {
      const original = btn.textContent;
      btn.textContent = '已复制';
      setTimeout(() => {
        btn.textContent = original;
      }, 1600);
    }
  } catch (e) {
    console.error('复制失败', e);
  }
}

function showError(message) {
  const errorBox = document.getElementById('error-box');
  if (!errorBox) return;
  if (message) {
    errorBox.textContent = message;
    errorBox.style.display = 'block';
  } else {
    errorBox.textContent = '';
    errorBox.style.display = 'none';
  }
}

function applySourceDefaults() {
  const sourceSelect = document.getElementById('source');
  if (!sourceSelect) return;
  const source = sourceSelect.value;
  const defaults = (window.sourceDefaults && window.sourceDefaults[source]) || {};
  const yearsInput = document.getElementById('years');
  const maxResultsInput = document.getElementById('max_results');
  const emailInput = document.getElementById('email');
  const apiKeyInput = document.getElementById('api_key');
  const outputInput = document.getElementById('output');

  if (yearsInput) {
    yearsInput.placeholder = defaults.years ? `默认 ${defaults.years}` : '';
  }
  if (maxResultsInput) {
    maxResultsInput.placeholder = defaults.max_results ? `默认 ${defaults.max_results}` : '';
  }
  if (emailInput) {
    emailInput.placeholder = defaults.email ? `默认 ${defaults.email}` : '用于 NCBI E-utilities 合规使用';
  }
  if (apiKeyInput) {
    apiKeyInput.placeholder = defaults.api_key ? `默认 ${defaults.api_key}` : '可选：例如 PubMed 的 NCBI API Key';
  }
  if (outputInput) {
    outputInput.placeholder = defaults.output ? `默认 ${defaults.output}` : '';
  }
}

function syncAiConfigState() {
  const providerSelect = document.getElementById('ai_provider');
  const value = providerSelect ? providerSelect.value : '';
  const isGemini = value === 'gemini';
  const isOpenAI = value === 'openai';
  const isOllama = value === 'ollama';
  const geminiBlock = document.getElementById('gemini-config');
  const openaiBlock = document.getElementById('openai-config');
  const ollamaBlock = document.getElementById('ollama-config');
  const hint = document.getElementById('ai-config-hint');

  const geminiFields = [
    document.getElementById('gemini_api_key'),
    document.getElementById('gemini_model'),
    document.getElementById('gemini_temperature'),
  ];
  const openaiFields = [
    document.getElementById('openai_api_key'),
    document.getElementById('openai_base_url'),
    document.getElementById('openai_model'),
    document.getElementById('openai_temperature'),
  ];
  const ollamaFields = [
    document.getElementById('ollama_api_key'),
    document.getElementById('ollama_base_url'),
    document.getElementById('ollama_model'),
    document.getElementById('ollama_temperature'),
  ];

  geminiFields.forEach((el) => {
    if (!el) return;
    el.disabled = !isGemini;
    el.style.opacity = isGemini ? '1' : '0.5';
  });
  openaiFields.forEach((el) => {
    if (!el) return;
    el.disabled = !isOpenAI;
    el.style.opacity = isOpenAI ? '1' : '0.5';
  });
  ollamaFields.forEach((el) => {
    if (!el) return;
    el.disabled = !isOllama;
    el.style.opacity = isOllama ? '1' : '0.5';
  });

  if (geminiBlock) {
    geminiBlock.style.display = isGemini ? 'flex' : 'none';
  }
  if (openaiBlock) {
    openaiBlock.style.display = isOpenAI ? 'flex' : 'none';
  }
  if (ollamaBlock) {
    ollamaBlock.style.display = isOllama ? 'flex' : 'none';
  }

  if (hint) {
    if (value === 'gemini') {
      hint.textContent = '当前使用 Gemini：可选填写下方参数，留空则使用系统环境变量 GEMINI_API_KEY 与默认模型 gemini-2.5-flash。';
    } else if (value === 'none') {
      hint.textContent = '当前未启用 AI 总结：仅执行检索与 BibTeX 生成。';
    } else if (value === 'openai') {
      hint.textContent = '当前使用 OpenAI 实时调用：可填写 Base URL/模型名称以兼容自托管接口。';
    } else if (value === 'ollama') {
      hint.textContent = '当前使用本地 Ollama：请确保已启动 Ollama 服务，Base URL 留空则默认 http://localhost:11434/v1。';
    } else {
      hint.textContent = '当前 AI 模型暂不需要额外配置。';
    }
  }
}

function wireHiddenBibtex() {
  const output = document.getElementById('bibtex-output');
  const hidden = document.getElementById('bibtex-hidden');
  if (output && hidden) {
    hidden.value = output.value;
  }
}

function createStatusItem(entry) {
  const li = document.createElement('li');
  li.className = 'status-item';
  const icon = document.createElement('span');
  icon.className = `status-icon ${entry.status || 'pending'}`;
  if (entry.status === 'success') icon.textContent = '✓';
  else if (entry.status === 'error') icon.textContent = '!';
  else if (entry.status === 'running') icon.textContent = '…';
  else icon.textContent = '…';
  const text = document.createElement('div');
  text.className = 'status-text';
  const strong = document.createElement('strong');
  strong.textContent = entry.step || '';
  const span = document.createElement('span');
  span.textContent = entry.detail || '';
  text.appendChild(strong);
  text.appendChild(span);
  li.appendChild(icon);
  li.appendChild(text);
  return li;
}

function resetStatusList() {
  const list = document.getElementById('status-list');
  if (!list) return;
  list.innerHTML = '';
  const placeholder = document.createElement('li');
  placeholder.className = 'status-item';
  placeholder.id = 'status-placeholder';
  const icon = document.createElement('span');
  icon.className = 'status-icon pending';
  icon.textContent = '…';
  const text = document.createElement('div');
  text.className = 'status-text';
  const strong = document.createElement('strong');
  strong.textContent = '等待开始';
  const span = document.createElement('span');
  span.textContent = '提交后实时显示进度。';
  text.appendChild(strong);
  text.appendChild(span);
  placeholder.appendChild(icon);
  placeholder.appendChild(text);
  list.appendChild(placeholder);
}

function appendStatus(entry) {
  const list = document.getElementById('status-list');
  if (!list) return;
  if (list.children.length && list.children[0].id === 'status-placeholder') {
    list.innerHTML = '';
  }
  list.appendChild(createStatusItem(entry));
}

function renderInitialStatus() {
  const initial = window.initialStatusLog || [];
  const list = document.getElementById('status-list');
  if (!list) return;
  if (!initial.length) return;
  list.innerHTML = '';
  initial.forEach((item) => list.appendChild(createStatusItem(item)));
}

let generatedQuery = '';
let runtimeTimer = null;
let runtimeStart = null;

function formatElapsed(seconds) {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

function setRuntimeState(text, tone) {
  const wrap = document.getElementById('runtime');
  const stateEl = document.getElementById('runtime-state');
  if (wrap) {
    wrap.setAttribute('data-tone', tone || 'idle');
  }
  if (stateEl) {
    stateEl.textContent = text;
  }
}

function updateRuntimeElapsed() {
  const elapsedEl = document.getElementById('runtime-elapsed');
  if (!elapsedEl || !runtimeStart) return;
  const seconds = Math.max(0, Math.floor((Date.now() - runtimeStart) / 1000));
  elapsedEl.textContent = formatElapsed(seconds);
}

function startRuntime() {
  runtimeStart = Date.now();
  updateRuntimeElapsed();
  setRuntimeState('运行中...', 'running');
  if (runtimeTimer) clearInterval(runtimeTimer);
  runtimeTimer = setInterval(updateRuntimeElapsed, 1000);
}

function stopRuntime(success = true, message = '') {
  if (runtimeTimer) {
    clearInterval(runtimeTimer);
    runtimeTimer = null;
  }
  updateRuntimeElapsed();
  if (runtimeStart) {
    const elapsedSeconds = Math.max(0, Math.floor((Date.now() - runtimeStart) / 1000));
    const prefix = success ? '已完成' : '运行失败';
    setRuntimeState(`${prefix}${message ? `：${message}` : ''} · ${formatElapsed(elapsedSeconds)}`, success ? 'success' : 'error');
  } else {
    setRuntimeState(success ? '已完成' : '运行失败', success ? 'success' : 'error');
  }
  runtimeStart = null;
}

async function generateQuery() {
  const intentInput = document.getElementById('intent');
  const messageBox = document.getElementById('generator-message');
  const previewBox = document.getElementById('generator-preview');
  const actions = document.getElementById('generator-preview-actions');
  const button = document.getElementById('btn-generate-query');
  if (!intentInput || !intentInput.value.trim()) {
    if (messageBox) messageBox.textContent = '请先输入你要检索的自然语言需求。';
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = '生成中...';
  }
  try {
    const body = {
      source: document.getElementById('source')?.value || '',
      intent: intentInput.value,
      ai_provider: document.getElementById('ai_provider')?.value || '',
      gemini_api_key: document.getElementById('gemini_api_key')?.value || '',
      gemini_model: document.getElementById('gemini_model')?.value || '',
      gemini_temperature: document.getElementById('gemini_temperature')?.value || '',
      openai_api_key: document.getElementById('openai_api_key')?.value || '',
      openai_base_url: document.getElementById('openai_base_url')?.value || '',
      openai_model: document.getElementById('openai_model')?.value || '',
      openai_temperature: document.getElementById('openai_temperature')?.value || '',
      ollama_api_key: document.getElementById('ollama_api_key')?.value || '',
      ollama_base_url: document.getElementById('ollama_base_url')?.value || '',
      ollama_model: document.getElementById('ollama_model')?.value || '',
      ollama_temperature: document.getElementById('ollama_temperature')?.value || '',
    };

    const resp = await fetch('/api/generate_query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    generatedQuery = data.query || '';
    if (messageBox) messageBox.textContent = data.message || '已生成预览。';
    if (previewBox) {
      previewBox.textContent = generatedQuery || '未生成检索式，请检查配置。';
      previewBox.style.display = generatedQuery ? 'block' : 'none';
    }
    if (actions) {
      actions.style.display = generatedQuery ? 'flex' : 'none';
    }
  } catch (err) {
    if (messageBox) {
      messageBox.textContent = '生成失败，请稍后重试或检查网络配置。';
    }
    console.error(err);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'AI 生成检索式';
    }
  }
}

function applyGeneratedQuery() {
  if (!generatedQuery) return;
  const queryInput = document.getElementById('query');
  if (queryInput) {
    queryInput.value = generatedQuery;
    queryInput.focus();
  }
}

function renderArticles(articles) {
  const container = document.getElementById('article-container');
  if (!container) return;
  if (!articles || !articles.length) {
    container.innerHTML = '<div class="hint">提交后将在此展示检索到的文献列表与 AI 总结。</div>';
    return;
  }
  const fragments = articles.map((article) => {
    const title = article.url
      ? `<a href="${article.url}" target="_blank" rel="noreferrer">${article.title}</a>`
      : article.title;
    const pmid = article.pmid ? `<span class="badge">PMID: ${article.pmid}</span>` : '';
    const abstractBlock = article.abstract
      ? `<div class="article-abstract"><span class="article-label">摘要：</span>${article.abstract}</div>`
      : '';
    const summaryBlock = article.summary_zh
      ? `<div class="article-summary"><span class="article-summary-label">AI 总结</span>${article.summary_zh}</div>`
      : '';
    const usageBlock = article.usage_zh
      ? `<div class="article-summary article-usage"><span class="article-summary-label">应用建议</span>${article.usage_zh}</div>`
      : '';
    return `
      <div class="article">
        <div class="article-title">${title}</div>
        <div class="article-meta">${article.authors} · ${article.journal} · ${article.year} ${pmid}</div>
        ${abstractBlock}
        ${summaryBlock}
        ${usageBlock}
      </div>
    `;
  });
  container.innerHTML = fragments.join('');
}

function updateBibtexResult(bibtexText, count) {
  const bibtexOutput = document.getElementById('bibtex-output');
  const resultCount = document.getElementById('result-count');
  const copyBtn = document.getElementById('copy-btn');
  const exportBtn = document.querySelector('.export-btn');
  const hidden = document.getElementById('bibtex-hidden');

  if (bibtexOutput) {
    bibtexOutput.value = bibtexText || '';
  }
  if (hidden) {
    hidden.value = bibtexText || '';
  }
  if (resultCount) {
    resultCount.textContent = `共 ${count || 0} 条记录`;
  }
  if (copyBtn) {
    copyBtn.disabled = !bibtexText;
  }
  if (exportBtn) {
    exportBtn.disabled = !bibtexText;
  }
}

function parseSseChunk(chunk) {
  const lines = chunk.split('\n');
  let eventType = 'message';
  let dataLine = '';
  lines.forEach((line) => {
    if (line.startsWith('event:')) {
      eventType = line.replace('event:', '').trim();
    } else if (line.startsWith('data:')) {
      dataLine += line.replace('data:', '').trim();
    }
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

  const form = document.getElementById('search-form');
  const submitBtn = document.getElementById('submit-btn');
  if (!form) return;

  resetStatusList();
  showError('');
  updateBibtexResult('', 0);
  renderArticles([]);
  startRuntime();

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = '运行中...';
  }

  const formData = new FormData(form);

  try {
    const resp = await fetch('/api/search_stream', {
      method: 'POST',
      body: formData,
    });
    if (!resp.ok || !resp.body) {
      throw new Error('接口返回异常');
    }
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
        const { eventType, payload } = parseSseChunk(part);
        if (eventType === 'status' && payload.entry) {
          appendStatus(payload.entry);
          if (payload.entry.status === 'error') {
            stopRuntime(false, payload.entry.detail || '');
          }
        }
        if (eventType === 'result') {
          updateBibtexResult(payload.bibtex_text, payload.count);
          renderArticles(payload.articles || []);
          stopRuntime(true, '');
        }
        if (eventType === 'error' && payload.message) {
          showError(payload.message);
          stopRuntime(false, payload.message);
        }
      });
    }
    if (buffer.trim()) {
      const { eventType, payload } = parseSseChunk(buffer.trim());
      if (eventType === 'status' && payload.entry) appendStatus(payload.entry);
      if (eventType === 'error' && payload.message) {
        showError(payload.message);
        stopRuntime(false, payload.message);
      }
      if (eventType === 'result') {
        updateBibtexResult(payload.bibtex_text, payload.count);
        renderArticles(payload.articles || []);
        stopRuntime(true, '');
      }
    }
  } catch (err) {
    console.error(err);
    showError('检索失败，请检查配置或网络。');
    stopRuntime(false, '接口异常或网络问题');
  } finally {
    if (runtimeStart) {
      stopRuntime(true, '');
    }
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = '检索并生成 BibTeX';
    }
  }
}

function wireEvents() {
  const sourceSelect = document.getElementById('source');
  if (sourceSelect) {
    sourceSelect.addEventListener('change', applySourceDefaults);
  }
  const aiSelect = document.getElementById('ai_provider');
  if (aiSelect) {
    aiSelect.addEventListener('change', syncAiConfigState);
  }
  const generatorButton = document.getElementById('btn-generate-query');
  if (generatorButton) {
    generatorButton.addEventListener('click', (e) => {
      e.preventDefault();
      generateQuery();
    });
  }

  const applyButton = document.getElementById('btn-apply-query');
  if (applyButton) {
    applyButton.addEventListener('click', applyGeneratedQuery);
  }

  const form = document.getElementById('search-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      if (e.submitter && e.submitter.classList.contains('export-btn')) {
        return;
      }
      streamSearch(e);
    });
  }

  const contactToggle = document.getElementById('toggle-contact');
  const contactBlock = document.getElementById('contact-advanced');
  if (contactToggle && contactBlock) {
    contactToggle.addEventListener('click', () => {
      const visible = contactBlock.style.display === 'block';
      contactBlock.style.display = visible ? 'none' : 'block';
      contactToggle.textContent = visible ? '显示 PubMed 邮箱/API' : '隐藏 PubMed 邮箱/API';
    });
  }
}

window.addEventListener('DOMContentLoaded', () => {
  applySourceDefaults();
  syncAiConfigState();
  wireHiddenBibtex();
  renderInitialStatus();
  wireEvents();
});
