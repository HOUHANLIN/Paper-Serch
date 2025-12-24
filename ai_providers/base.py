from typing import Protocol

from paper_sources import ArticleInfo


class AiProvider(Protocol):
    name: str
    display_name: str

    def summarize(self, info: ArticleInfo) -> str:
        ...
