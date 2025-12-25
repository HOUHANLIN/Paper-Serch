from typing import Protocol

from app.sources import ArticleInfo


class AiProvider(Protocol):
    name: str
    display_name: str

    def summarize(self, info: ArticleInfo) -> str:
        ...
