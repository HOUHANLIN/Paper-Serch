"""Placeholder OpenAI provider for future expansion."""
from paper_sources import ArticleInfo

from .base import AiProvider


class OpenAIProvider(AiProvider):
    name = "openai"
    display_name = "OpenAI (占位)"

    def summarize(self, info: ArticleInfo) -> str:  # pragma: no cover - placeholder
        # This is intentionally left minimal so future developers can plug in
        # actual OpenAI API calls without changing the web or registry layers.
        return ""
