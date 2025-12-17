from __future__ import annotations

"""Reusable AI summary helpers."""

import json
import re
from typing import List, Tuple

from ai_providers.gemini import GeminiProvider
from ai_providers.ollama import OllamaProvider
from ai_providers.openai_provider import OpenAIProvider
from ai_providers.registry import get_provider
from paper_sources import ArticleInfo


def normalize_annote(raw: str) -> Tuple[str, str, str]:
    """Normalize annote content and try to extract summary/usage fields."""

    text = (raw or "").strip()
    if not text:
        return "", "", ""

    candidates: List[str] = []

    def _add_candidate(val: str) -> None:
        if val and val not in candidates:
            candidates.append(val)

    _add_candidate(text)

    fence_trimmed = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    _add_candidate(fence_trimmed)

    match = re.search(r"\{.*\}", fence_trimmed, flags=re.DOTALL)
    if match:
        _add_candidate(match.group(0).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            summary = str(parsed.get("summary_zh") or "").strip()
            usage = str(parsed.get("usage_zh") or "").strip()
            normalized_json = json.dumps(
                {k: v for k, v in (("summary_zh", summary), ("usage_zh", usage)) if v},
                ensure_ascii=False,
            )
            return normalized_json, summary, usage

    return fence_trimmed, fence_trimmed, ""


def apply_ai_summary(
    infos: List[ArticleInfo],
    provider_name: str,
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
) -> str:
    """Apply AI summary generation to a list of articles."""

    provider = get_provider(provider_name)
    if not provider or provider.name == "none":
        return "已跳过 AI 总结（未选择模型）"

    if isinstance(provider, GeminiProvider):
        provider.set_config(
            api_key=gemini_api_key or None,
            model=gemini_model or None,
            temperature=gemini_temperature,
        )
    if isinstance(provider, OpenAIProvider):
        provider.set_config(
            api_key=openai_api_key or None,
            base_url=openai_base_url or None,
            model=openai_model or None,
            temperature=openai_temperature,
        )
    if isinstance(provider, OllamaProvider):
        provider.set_config(
            api_key=ollama_api_key or None,
            base_url=ollama_base_url or None,
            model=ollama_model or None,
            temperature=ollama_temperature,
        )

    applied = 0
    for info in infos:
        summary = provider.summarize(info)
        if summary:
            info.annote, _, _ = normalize_annote(summary)
            applied += 1
    if applied:
        return f"已使用 {provider.display_name} 生成 {applied} 条摘要"
    return "AI 未返回摘要，可能未配置模型或接口未返回内容"
