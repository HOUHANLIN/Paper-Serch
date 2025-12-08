import datetime as _dt
import os
from typing import Dict, List, Optional

import requests

from paper_sources import ArticleInfo, PaperSource
from services.env_loader import load_env
from services.keys import build_cite_key


class EmbaseSource(PaperSource):
    """Embase via Elsevier API."""

    name = "embase"
    display_name = "Embase"

    SEARCH_URL = "https://api.elsevier.com/content/search/embase"

    def search(
        self,
        query: str,
        years: int = 5,
        max_results: int = 10,
        *,
        api_key: Optional[str] = None,
        insttoken: Optional[str] = None,
        **_: Dict,
    ) -> List[ArticleInfo]:
        load_env()

        api_key = api_key or os.environ.get("EMBASE_API_KEY")
        insttoken = insttoken or os.environ.get("EMBASE_INSTTOKEN") or os.environ.get("ELS_INSTTOKEN")
        if not api_key:
            raise ValueError("Embase API key is required. Set EMBASE_API_KEY in .env.")

        today = _dt.date.today()
        start_year = today.year - years + 1 if years > 0 else today.year
        year_filter = f"PUBYEAR > {start_year - 1}" if years else ""
        search_query = query if not year_filter else f"{query} AND {year_filter}"

        headers = {"Accept": "application/json", "X-ELS-APIKey": api_key}
        if insttoken:
            headers["X-ELS-Insttoken"] = insttoken

        params = {"query": search_query, "count": max_results, "sort": "relevance"}

        resp = requests.get(self.SEARCH_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        entries = data.get("search-results", {}).get("entry", [])
        results: List[ArticleInfo] = []
        for entry in entries:
            results.append(self._to_article_info(entry))
        return results

    def _to_article_info(self, entry: Dict) -> ArticleInfo:
        def _first_value(values: Optional[List[Dict]]) -> str:
            if isinstance(values, list) and values:
                val = values[0]
                if isinstance(val, dict):
                    return str(val.get("$") or "").strip()
                return str(val).strip()
            return ""

        title = str(entry.get("dc:title") or "").strip()

        authors_raw = entry.get("dc:creator")
        authors: List[str] = []
        if isinstance(authors_raw, list):
            for val in authors_raw:
                if isinstance(val, dict) and val.get("$"):
                    authors.append(str(val["$"]).strip())
                elif isinstance(val, str):
                    authors.append(val.strip())
        elif isinstance(authors_raw, str):
            authors.append(authors_raw.strip())

        journal = str(entry.get("prism:publicationName") or "").strip()
        cover_date = str(entry.get("prism:coverDate") or "").strip()
        year = cover_date.split("-")[0] if cover_date else ""
        volume = str(entry.get("prism:volume") or "").strip()
        issue = str(entry.get("prism:issueIdentifier") or "").strip()
        pages = str(entry.get("prism:pageRange") or "").strip()
        doi = str(entry.get("prism:doi") or "").strip()
        abstract = str(entry.get("dc:description") or "").strip()
        keywords = ""

        issn = str(entry.get("prism:issn") or "").strip()
        eissn = str(entry.get("prism:eIssn") or "").strip()
        article_type = str(entry.get("subtypeDescription") or "").strip()

        url = str(entry.get("prism:url") or "").strip()
        if not url:
            url = _first_value(entry.get("link"))

        identifier = str(entry.get("dc:identifier") or entry.get("eid") or "").strip()
        first_author_last = authors[0].split(",")[0] if authors else ""
        cite_key = build_cite_key(first_author_last, year or "n.d.", identifier)

        return ArticleInfo(
            pmid=identifier,
            title=title,
            journal=journal,
            year=year,
            volume=volume,
            issue=issue,
            pages=pages,
            authors=" and ".join(authors),
            doi=doi,
            abstract=abstract,
            keywords=keywords,
            mesh_terms="",
            language="",
            article_type=article_type,
            affiliation="",
            issn=issn,
            eissn=eissn,
            url=url,
            pmcid="",
            key=cite_key,
        )


def get_default_embase_source() -> EmbaseSource:
    return EmbaseSource()
