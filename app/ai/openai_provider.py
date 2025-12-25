"""OpenAI provider with real API calls for summaries."""
import os
import sys
from typing import Optional

from openai import OpenAI

from app.sources import ArticleInfo

from .base import AiProvider


class OpenAIProvider(AiProvider):
    name = "openai"
    display_name = "OpenAI (实时调用)"

    def __init__(self) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY")
        self.base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE")
        self.model = os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        self.temperature = self._get_temperature()
        self._client: Optional[OpenAI] = None

    def _get_temperature(self) -> float:
        try:
            return float(os.environ.get("OPENAI_TEMPERATURE", "0"))
        except ValueError:
            return 0.0

    def set_config(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> None:
        changed = False
        if api_key is not None and api_key != self.api_key:
            self.api_key = api_key
            changed = True
        if base_url is not None and base_url != self.base_url:
            self.base_url = base_url
            changed = True
        if model is not None and model != self.model:
            self.model = model
            changed = True
        if temperature is not None and temperature != self.temperature:
            self.temperature = temperature
            changed = True
        if changed:
            self._client = None

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        if not self.api_key:
            return False
        try:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url or None)
            return True
        except Exception as exc:  # pragma: no cover - external lib init
            print(f"警告: 初始化 OpenAI 客户端失败: {exc}", file=sys.stderr)
            return False

    def summarize(self, info: ArticleInfo) -> str:
        if not self._ensure_client():
            return ""
        abstract = (info.abstract or "").strip()
        if not abstract:
            return ""

        title = (info.title or "").strip()
        journal = (info.journal or "").strip()
        year = (info.year or "").strip()

        system_prompt = (
            "你是一名医学文献综述助手，请根据给定的题目和摘要，输出一个 JSON 对象，"
            "仅包含以下两个字段：\n"
            "{\n"
            '  "summary_zh": "用中文 2-4 句话概括文章的研究目的、方法和主要结论",\n'
            '  "usage_zh": "用中文说明在撰写综述或论文时，这篇文章可以如何被引用或使用，'
            '例如适合放在背景、方法、结果讨论中的哪一部分，以及它支持/补充了哪些观点"\n'
            "}\n\n"
            "只输出合法 JSON，不要输出任何解释性文字或 Markdown。"
        )
        user_prompt = (
            f"标题: {title}\n期刊: {journal}\n年份: {year}\n摘要: {abstract}\n"
            "请输出 JSON，字段值保持简洁。"
        )

        try:
            client = self._client
            if client is None:  # pragma: no cover - defensive
                return ""
            completion = client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=320,
            )
            content = completion.choices[0].message.content if completion.choices else ""
            return (content or "").strip()
        except Exception as exc:  # pragma: no cover - external service errors
            print(
                f"警告: 生成 OpenAI 总结失败（PMID {info.pmid}）: {exc}",
                file=sys.stderr,
            )
            return ""
