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

function applySourceDefaults() {
  const source = document.getElementById('source').value;
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
  const geminiBlock = document.getElementById('gemini-config');
  const openaiBlock = document.getElementById('openai-config');
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

  if (geminiBlock) {
    geminiBlock.style.display = isGemini ? 'flex' : 'none';
  }
  if (openaiBlock) {
    openaiBlock.style.display = isOpenAI ? 'flex' : 'none';
  }

  if (hint) {
    if (value === 'gemini') {
      hint.textContent = '当前使用 Gemini：可选填写下方参数，留空则使用系统环境变量 GEMINI_API_KEY 与默认模型 gemini-2.5-flash。';
    } else if (value === 'none') {
      hint.textContent = '当前未启用 AI 总结：仅执行检索与 BibTeX 生成。';
    } else if (value === 'openai') {
      hint.textContent = '当前使用 OpenAI 实时调用：可填写 Base URL/模型名称以兼容自托管接口。';
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

async function generateQuery() {
  const intentInput = document.getElementById('intent');
  const outputBox = document.getElementById('generator-output');
  const button = document.getElementById('btn-generate-query');
  if (!intentInput || !intentInput.value.trim()) {
    outputBox.textContent = '请先输入你要检索的自然语言需求。';
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
    };

    const resp = await fetch('/api/generate_query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (outputBox) {
      outputBox.textContent = data.message || '';
    }
    if (data.query) {
      const queryInput = document.getElementById('query');
      if (queryInput) {
        queryInput.value = data.query;
      }
    }
  } catch (err) {
    if (outputBox) {
      outputBox.textContent = '生成失败，请稍后重试或检查网络配置。';
    }
    console.error(err);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'AI 生成检索式';
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
}

window.addEventListener('DOMContentLoaded', () => {
  applySourceDefaults();
  syncAiConfigState();
  wireHiddenBibtex();
  wireEvents();
});
