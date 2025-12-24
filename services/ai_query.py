from __future__ import annotations

import re
from typing import List, Optional, Tuple

from openai import OpenAI

from ai_providers.gemini import GeminiProvider
from ai_providers.ollama import OllamaProvider
from ai_providers.openai_provider import OpenAIProvider


def build_pubmed_query_by_rules(intent: str) -> str:
    intent_clean = intent.strip()
    if not intent_clean:
        return ""

    segments = re.split(r"[；;，。,.]+", intent_clean)
    groups: List[str] = []
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        synonyms = re.split(r"\s*(?:或|或者|or|OR|/|\|)\s*", segment)
        synonym_terms: List[str] = []
        for term in synonyms:
            term_clean = term.strip()
            if not term_clean:
                continue
            if " " in term_clean or "“" in term_clean or '"' in term_clean:
                synonym_terms.append(f'("{term_clean.strip("\" ")}"[Title/Abstract])')
            else:
                synonym_terms.append(f"({term_clean}[Title/Abstract])")
        if synonym_terms:
            if len(synonym_terms) == 1:
                groups.append(synonym_terms[0])
            else:
                groups.append("(" + " OR ".join(synonym_terms) + ")")
    return " AND ".join(groups)


def _generate_query_via_openai(prompt: str, api_key: str, base_url: str, model: str, temperature: float) -> str:
    try:
        client = OpenAI(api_key=api_key, base_url=base_url or None)
        completion = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": "你是检索词专家，只输出最终的检索式文本，不要解释。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=320,
        )
        content = completion.choices[0].message.content if completion.choices else ""
        return (content or "").strip()
    except Exception:
        return ""


def _generate_query_via_gemini(prompt: str, api_key: str, model: str, temperature: float) -> str:
    provider = GeminiProvider()
    provider.set_config(api_key=api_key, model=model or None, temperature=temperature)
    if not provider._ensure_client():  # pylint: disable=protected-access
        return ""
    try:
        types = provider._types  # pylint: disable=protected-access
        client = provider._client  # pylint: disable=protected-access
        if types is None or client is None:
            return ""
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
        config = types.GenerateContentConfig(temperature=temperature)
        chunks: List[str] = []
        for chunk in client.models.generate_content_stream(model=provider.model, contents=contents, config=config):
            text = getattr(chunk, "text", "") or ""
            if text:
                chunks.append(text)
        return " ".join(chunks).strip()
    except Exception:
        return ""


def _generate_query_via_ollama(prompt: str, api_key: str, base_url: str, model: str, temperature: float) -> str:
    try:
        client = OpenAI(api_key=api_key or "ollama", base_url=base_url or "http://localhost:11434/v1")
        completion = client.chat.completions.create(
            model=model or "llama3.1",
            temperature=temperature,
            messages=[
                {
                    "role": "system",
                    "content": "你是检索词专家，只输出最终的检索式文本，不要解释。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=320,
        )
        content = completion.choices[0].message.content if completion.choices else ""
        return (content or "").strip()
    except Exception:
        return ""


def generate_query_terms(
    *,
    source_name: str,
    intent: str,
    ai_provider: str,
    gemini_api_key: str,
    gemini_model: str,
    gemini_temperature: float,
    openai_api_key: str,
    openai_base_url: str,
    openai_model: str,
    openai_temperature: float,
    ollama_api_key: str,
    ollama_base_url: str,
    ollama_model: str,
    ollama_temperature: float,
) -> Tuple[str, str]:
    def _normalize(value: str) -> str:
        return (value or "").strip()

    def _normalize_optional(value: str) -> Optional[str]:
        value_clean = (value or "").strip()
        return value_clean or None

    intent_clean = (intent or "").strip()
    if not intent_clean:
        return "", "请先提供你的检索需求。"

    if source_name == "pubmed":
        syntax_hint = (
            "请输出 PubMed 检索式：概念用 AND 连接，同义词用 OR 连接，短语加引号，"
            "并可使用 [Title/Abstract] 字段限制。不要添加额外解释。"
        )
    else:
        syntax_hint = "请给出适配所选文献站点的检索式，不要额外解释。"

    prompt = (
        f"用户需求：{intent_clean}\n"
        f"目标站点：{source_name}\n"
        f"格式要求：{syntax_hint}\n"
        "请直接返回最终检索式。"
    )

    openai_defaults = OpenAIProvider()
    resolved_openai_api_key = _normalize(openai_api_key) or (openai_defaults.api_key or "")
    resolved_openai_base_url = _normalize_optional(openai_base_url) or openai_defaults.base_url or ""
    resolved_openai_model = _normalize(openai_model) or openai_defaults.model
    resolved_openai_temperature = openai_temperature if openai_temperature is not None else openai_defaults.temperature

    gemini_defaults = GeminiProvider()
    resolved_gemini_api_key = _normalize(gemini_api_key) or (gemini_defaults.api_key or "")
    resolved_gemini_model = _normalize(gemini_model) or gemini_defaults.model
    resolved_gemini_temperature = gemini_temperature if gemini_temperature is not None else gemini_defaults.temperature

    ollama_defaults = OllamaProvider()
    resolved_ollama_api_key = _normalize(ollama_api_key) or (ollama_defaults.api_key or "ollama")
    resolved_ollama_base_url = _normalize_optional(ollama_base_url) or ollama_defaults.base_url or ""
    resolved_ollama_model = _normalize(ollama_model) or ollama_defaults.model
    resolved_ollama_temperature = ollama_temperature if ollama_temperature is not None else ollama_defaults.temperature

    if ai_provider == "openai":
        if not resolved_openai_api_key:
            return "", "未配置 OpenAI API Key，无法调用真实接口生成检索式。"
        ai_query = _generate_query_via_openai(
            prompt,
            resolved_openai_api_key,
            resolved_openai_base_url,
            resolved_openai_model,
            resolved_openai_temperature,
        )
        if ai_query:
            return ai_query, "已使用 OpenAI 实时生成的检索式"
        return "", "OpenAI 生成检索式失败，请检查配置。"

    if ai_provider == "gemini":
        if not resolved_gemini_api_key:
            return "", "未配置 Gemini API Key，无法调用真实接口生成检索式。"
        ai_query = _generate_query_via_gemini(
            prompt,
            resolved_gemini_api_key,
            resolved_gemini_model,
            resolved_gemini_temperature,
        )
        if ai_query:
            return ai_query, "已使用 Gemini 实时生成的检索式"
        return "", "Gemini 生成检索式失败，请检查配置。"

    if ai_provider == "ollama":
        if not resolved_ollama_base_url:
            return "", "未配置 Ollama Base URL，无法调用本地接口生成检索式。"
        ai_query = _generate_query_via_ollama(
            prompt,
            resolved_ollama_api_key,
            resolved_ollama_base_url,
            resolved_ollama_model,
            resolved_ollama_temperature,
        )
        if ai_query:
            return ai_query, "已使用 Ollama 实时生成的检索式"
        return "", "Ollama 生成检索式失败，请检查配置。"

    if source_name == "pubmed":
        return build_pubmed_query_by_rules(intent_clean), "已按规则生成 PubMed 检索式"

    return intent_clean, "已返回原始输入"
