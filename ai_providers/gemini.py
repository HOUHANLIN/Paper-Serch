import os
import sys
import os
import sys
from typing import Optional

from paper_sources import ArticleInfo

from .base import AiProvider


class GeminiProvider(AiProvider):
    name = "gemini"
    display_name = "Gemini"

    def __init__(self) -> None:
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.model = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
        self.temperature = self._get_temperature()
        self._client = None
        self._types = None

    def _get_temperature(self) -> float:
        try:
            return float(os.environ.get("GEMINI_TEMPERATURE", "0"))
        except ValueError:
            return 0.0

    def set_config(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> None:
        changed = False
        if api_key is not None and api_key != self.api_key:
            self.api_key = api_key
            changed = True
        if model is not None and model != self.model:
            self.model = model
            changed = True
        if temperature is not None and temperature != self.temperature:
            self.temperature = temperature
            changed = True
        if changed:
            self._client = None
            self._types = None

    def _ensure_client(self) -> bool:
        if self._client is not None and self._types is not None:
            return True
        if not self.api_key or not self.model:
            return False
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore
        except Exception as exc:  # pragma: no cover - import error path
            print(
                f"警告: 导入 google-genai 失败，将跳过 AI 总结: {exc}",
                file=sys.stderr,
            )
            return False
        try:
            self._client = genai.Client(api_key=self.api_key)
            self._types = types
            return True
        except Exception as exc:  # pragma: no cover - runtime config error
            print(
                f"警告: 初始化 Gemini 客户端失败，将跳过 AI 总结: {exc}",
                file=sys.stderr,
            )
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

        prompt = (
            "你是一名医学文献综述助手，请根据给定的题目和摘要，输出一个 JSON 对象，"
            "仅包含以下两个字段（不要添加其它字段）：\n"
            "{\n"
            '  "summary_zh": "用中文 2-4 句话概括文章的研究目的、方法和主要结论",\n'
            '  "usage_zh": "用中文说明在撰写综述或论文时，这篇文章可以如何被引用或使用，'
            '例如适合放在背景、方法、结果讨论中的哪一部分，以及它支持/补充了哪些观点"\n'
            "}\n\n"
            "输出要求：\n"
            "1. 只输出合法 JSON，不要输出任何解释性文字或 Markdown。\n"
            "2. 字段值必须是简短的中文自然段，不要出现换行符。\n"
            "3. 如与口腔种植学（dental implants）或种植导板、术前规划等相关，请在 summary_zh 中点明。\n\n"
            f"文献信息如下：\n"
            f"标题: {title}\n"
            f"期刊: {journal}\n"
            f"年份: {year}\n"
            f"摘要: {abstract}"
        )

        try:
            types = self._types
            client = self._client
            if types is None or client is None:  # pragma: no cover - defensive
                return ""
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                )
            ]
            config = types.GenerateContentConfig(temperature=self.temperature)
            chunks = []
            for chunk in client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            ):
                text = getattr(chunk, "text", "") or ""
                if text:
                    chunks.append(text)
            return " ".join(chunks).strip()
        except Exception as exc:  # pragma: no cover - external service errors
            print(
                f"警告: 生成 AI 总结失败（PMID {info.pmid}）: {exc}",
                file=sys.stderr,
            )
            return ""


def get_default_gemini_provider() -> Optional[GeminiProvider]:
    return GeminiProvider()
