"""Utilities for extracting search directions via AI providers."""
from __future__ import annotations

import re
from typing import List, Tuple

from ai_providers.gemini import GeminiProvider
from ai_providers.ollama import OllamaProvider
from ai_providers.openai_provider import OpenAIProvider
from openai import OpenAI


_SYSTEM_DIRECTION_PROMPT = (
    "你是科研助理，请从给定的文本中提取 3-6 个可用于学术检索的方向，"
    "每行只输出一个方向的简洁标题，不要解释，不要编号。"
)


def _extract_directions_via_openai(
    prompt: str, api_key: str, base_url: str, model: str, temperature: float
) -> str:
    client = OpenAI(api_key=api_key, base_url=base_url or None)
    completion = client.chat.completions.create(
        model=model or "gpt-4o-mini",
        temperature=temperature,
        messages=[
            {"role": "system", "content": _SYSTEM_DIRECTION_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=480,
    )
    content = completion.choices[0].message.content if completion.choices else ""
    return (content or "").strip()


def _extract_directions_via_ollama(
    prompt: str, api_key: str, base_url: str, model: str, temperature: float
) -> str:
    client = OpenAI(api_key=api_key or "ollama", base_url=base_url or "http://localhost:11434/v1")
    completion = client.chat.completions.create(
        model=model or "llama3.1",
        temperature=temperature,
        messages=[
            {"role": "system", "content": _SYSTEM_DIRECTION_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=480,
    )
    content = completion.choices[0].message.content if completion.choices else ""
    return (content or "").strip()


def _extract_directions_via_gemini(prompt: str, api_key: str, model: str, temperature: float) -> str:
    provider = GeminiProvider()
    provider.set_config(api_key=api_key, model=model or None, temperature=temperature)
    if not provider._ensure_client():  # pylint: disable=protected-access
        return ""

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


def _parse_direction_lines(raw: str) -> List[str]:
    lines: List[str] = []
    for line in (raw or "").splitlines():
        cleaned = re.sub(r"^[\s\d\.-:：•、]+", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def extract_search_directions(
    *,
    content: str,
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
) -> Tuple[List[str], str]:
    """Use the configured AI provider to extract searchable directions."""
    content_clean = (content or "").strip()
    if not content_clean:
        return [], "请先提供要分析的文本。"

    prompt = "请阅读以下文本，提炼适合学术文献检索的方向（每行一个、无需编号）：\n" + content_clean

    openai_defaults = OpenAIProvider()
    resolved_openai_api_key = (openai_api_key or openai_defaults.api_key or "").strip()
    resolved_openai_base_url = (openai_base_url or openai_defaults.base_url or "").strip()
    resolved_openai_model = (openai_model or openai_defaults.model or "").strip()
    resolved_openai_temperature = openai_temperature if openai_temperature is not None else openai_defaults.temperature

    gemini_defaults = GeminiProvider()
    resolved_gemini_api_key = (gemini_api_key or gemini_defaults.api_key or "").strip()
    resolved_gemini_model = (gemini_model or gemini_defaults.model or "").strip()
    resolved_gemini_temperature = gemini_temperature if gemini_temperature is not None else gemini_defaults.temperature

    ollama_defaults = OllamaProvider()
    resolved_ollama_api_key = (ollama_api_key or ollama_defaults.api_key or "ollama").strip()
    resolved_ollama_base_url = (ollama_base_url or ollama_defaults.base_url or "").strip()
    resolved_ollama_model = (ollama_model or ollama_defaults.model or "").strip()
    resolved_ollama_temperature = ollama_temperature if ollama_temperature is not None else ollama_defaults.temperature

    raw_output = ""
    try:
        if ai_provider == "openai":
            if not resolved_openai_api_key:
                return [], "未配置 OpenAI API Key，无法提取检索方向。"
            raw_output = _extract_directions_via_openai(
                prompt,
                resolved_openai_api_key,
                resolved_openai_base_url,
                resolved_openai_model,
                resolved_openai_temperature,
            )
        elif ai_provider == "gemini":
            if not resolved_gemini_api_key:
                return [], "未配置 Gemini API Key，无法提取检索方向。"
            raw_output = _extract_directions_via_gemini(
                prompt,
                resolved_gemini_api_key,
                resolved_gemini_model,
                resolved_gemini_temperature,
            )
        elif ai_provider == "ollama":
            raw_output = _extract_directions_via_ollama(
                prompt,
                resolved_ollama_api_key,
                resolved_ollama_base_url,
                resolved_ollama_model,
                resolved_ollama_temperature,
            )
        else:
            return [], "当前未选择可用的 AI 提取方式。"
    except Exception as exc:  # pylint: disable=broad-except
        return [], f"AI 提取检索方向失败：{exc}"

    directions = _parse_direction_lines(raw_output)
    if not directions:
        return [], "AI 未返回有效的检索方向，请检查配置。"
    return directions, f"已提取 {len(directions)} 个检索方向"
