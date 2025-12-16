from dataclasses import dataclass
from dataclasses import dataclass
from typing import List, Protocol


@dataclass
class ArticleInfo:
    pmid: str = ""
    title: str = ""
    journal: str = ""
    year: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    authors: str = ""
    doi: str = ""
    abstract: str = ""
    keywords: str = ""
    mesh_terms: str = ""
    language: str = ""
    article_type: str = ""
    affiliation: str = ""
    issn: str = ""
    eissn: str = ""
    url: str = ""
    pmcid: str = ""
    annote: str = ""
    key: str = ""


class PaperSource(Protocol):
    """A source that can search for articles and provide structured metadata."""

    name: str
    display_name: str

    def search(self, query: str, years: int, max_results: int, **kwargs) -> List[ArticleInfo]:
        ...
