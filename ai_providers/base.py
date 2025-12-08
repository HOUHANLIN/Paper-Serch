from typing import Protocol

from paper_sources import ArticleInfo


class AiProvider(Protocol):
    name: str
    display_name: str

    def summarize(self, info: ArticleInfo) -> str:
        ...


class NoopAiProvider:
    name = "none"
    display_name = "不使用 AI 总结"

    def summarize(self, info: ArticleInfo) -> str:  # pragma: no cover - trivial passthrough
        return ""
