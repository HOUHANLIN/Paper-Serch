import datetime as _dt
import os
import random
import threading
import time
import xml.etree.ElementTree as ET
from typing import List, Optional

import requests
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

from paper_sources import ArticleInfo, PaperSource
from services.keys import build_cite_key


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_PUBMED_MAX_CONCURRENT_REQUESTS = max(1, int(os.environ.get("PUBMED_MAX_CONCURRENT_REQUESTS", "3")))
_PUBMED_REQUEST_SEMAPHORE = threading.BoundedSemaphore(_PUBMED_MAX_CONCURRENT_REQUESTS)

_PUBMED_MAX_RETRIES = max(0, int(os.environ.get("PUBMED_MAX_RETRIES", "4")))
try:
    _PUBMED_BACKOFF_BASE = float(os.environ.get("PUBMED_BACKOFF_BASE", "0.6"))
except (TypeError, ValueError):
    _PUBMED_BACKOFF_BASE = 0.6
try:
    _PUBMED_BACKOFF_MAX = float(os.environ.get("PUBMED_BACKOFF_MAX", "10"))
except (TypeError, ValueError):
    _PUBMED_BACKOFF_MAX = 10.0
_PUBMED_RETRY_STATUS = {429, 500, 502, 503, 504}


def _safe_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sleep_backoff(attempt: int, *, retry_after_seconds: Optional[int] = None) -> None:
    if retry_after_seconds is not None and retry_after_seconds > 0:
        time.sleep(min(float(retry_after_seconds), _PUBMED_BACKOFF_MAX))
        return
    base = max(0.0, _PUBMED_BACKOFF_BASE)
    delay = min(_PUBMED_BACKOFF_MAX, base * (2**attempt))
    jitter = random.uniform(0.0, min(0.5, delay)) if delay > 0 else 0.0
    time.sleep(delay + jitter)


class PubMedSource(PaperSource):
    name = "pubmed"
    display_name = "PubMed"

    def _get_with_retry(
        self,
        url: str,
        *,
        params: dict,
        timeout: int,
        semaphore: threading.Semaphore,
        label: str,
    ) -> Response:
        last_error: Optional[str] = None
        for attempt in range(_PUBMED_MAX_RETRIES + 1):
            try:
                with semaphore:
                    resp = requests.get(url, params=params, timeout=timeout)
                status_code = int(resp.status_code)

                if status_code in _PUBMED_RETRY_STATUS:
                    retry_after = _safe_int(resp.headers.get("Retry-After", ""))
                    last_error = f"{label} 返回 {status_code}"
                    if attempt < _PUBMED_MAX_RETRIES:
                        _sleep_backoff(attempt, retry_after_seconds=retry_after)
                        continue
                    if status_code == 429:
                        raise RuntimeError(
                            f"{label} 被限流（HTTP 429）。请降低 PubMed 并发（页面“PubMed 并发”或环境变量 "
                            "PUBMED_MAX_CONCURRENT_REQUESTS），或稍后重试。"
                        )
                    raise RuntimeError(f"{label} 服务暂时不可用（HTTP {status_code}），请稍后重试。")
                if status_code >= 400:
                    snippet = (resp.text or "").strip().replace("\n", " ")
                    if len(snippet) > 240:
                        snippet = snippet[:240] + "..."
                    if status_code == 400:
                        raise RuntimeError(
                            f"{label} 请求被拒绝（HTTP 400）。可能是检索式不合法/过长。返回：{snippet or '无返回内容'}"
                        )
                    raise RuntimeError(f"{label} 请求失败（HTTP {status_code}）：{snippet or '无返回内容'}")

                return resp
            except (Timeout, RequestsConnectionError) as exc:
                last_error = f"{label} 连接失败：{exc}"
                if attempt < _PUBMED_MAX_RETRIES:
                    _sleep_backoff(attempt)
                    continue
                raise RuntimeError(
                    f"{label} 多次连接失败（已重试 {_PUBMED_MAX_RETRIES} 次）：{exc}"
                ) from exc
            except RequestException as exc:
                last_error = f"{label} 请求异常：{exc}"
                if attempt < _PUBMED_MAX_RETRIES:
                    _sleep_backoff(attempt)
                    continue
                raise RuntimeError(f"{label} 请求异常（已重试 {_PUBMED_MAX_RETRIES} 次）：{exc}") from exc

        raise RuntimeError(last_error or f"{label} 请求失败")

    def search(
        self,
        query: str,
        years: int = 5,
        max_results: int = 10,
        *,
        email: Optional[str] = None,
        api_key: Optional[str] = None,
        pubmed_semaphore: Optional[threading.Semaphore] = None,
    ) -> List[ArticleInfo]:
        pmids = self._search_pubmed(
            query, years, max_results, email=email, api_key=api_key, pubmed_semaphore=pubmed_semaphore
        )
        if not pmids:
            return []

        root = self._fetch_pubmed_details(pmids, email=email, api_key=api_key, pubmed_semaphore=pubmed_semaphore)
        return [self._extract_article_info(article) for article in root.findall("PubmedArticle")]

    def _search_pubmed(
        self,
        query: str,
        years: int,
        max_results: int,
        *,
        email: Optional[str],
        api_key: Optional[str],
        pubmed_semaphore: Optional[threading.Semaphore],
    ) -> List[str]:
        today = _dt.date.today()
        years = max(0, int(years or 0))
        start_date = today - _dt.timedelta(days=365 * years)
        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": str(max_results),
            "sort": "best match",
            "datetype": "pdat",
            "mindate": start_date.strftime("%Y/%m/%d"),
            "maxdate": today.strftime("%Y/%m/%d"),
        }
        if email:
            params["email"] = email
        if api_key:
            params["api_key"] = api_key

        semaphore = pubmed_semaphore or _PUBMED_REQUEST_SEMAPHORE
        resp = self._get_with_retry(
            f"{EUTILS_BASE}/esearch.fcgi",
            params=params,
            timeout=20,
            semaphore=semaphore,
            label="PubMed 检索（esearch）",
        )
        try:
            data = resp.json()
        except Exception as exc:
            snippet = (resp.text or "").strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240] + "..."
            raise RuntimeError(f"PubMed 检索返回非 JSON：{snippet or '无返回内容'}") from exc

        id_list = data.get("esearchresult", {}).get("idlist", [])
        return id_list[:max_results]

    def _fetch_pubmed_details(
        self,
        pmids: List[str],
        *,
        email: Optional[str],
        api_key: Optional[str],
        pubmed_semaphore: Optional[threading.Semaphore],
    ) -> ET.Element:
        if not pmids:
            raise ValueError("No PMIDs provided")

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        if email:
            params["email"] = email
        if api_key:
            params["api_key"] = api_key

        semaphore = pubmed_semaphore or _PUBMED_REQUEST_SEMAPHORE
        resp = self._get_with_retry(
            f"{EUTILS_BASE}/efetch.fcgi",
            params=params,
            timeout=30,
            semaphore=semaphore,
            label="PubMed 详情（efetch）",
        )
        try:
            return ET.fromstring(resp.text)
        except Exception as exc:
            snippet = (resp.text or "").strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240] + "..."
            raise RuntimeError(f"PubMed 详情返回 XML 解析失败：{snippet or '无返回内容'}") from exc

    @staticmethod
    def _get_text(elem: Optional[ET.Element]) -> str:
        if elem is None:
            return ""

        parts = []
        for text in elem.itertext():
            text = (text or "").strip()
            if text:
                parts.append(text)
        return " ".join(parts)

    def _extract_article_info(self, article: ET.Element) -> ArticleInfo:
        medline = article.find("MedlineCitation")
        article_elem = medline.find("Article") if medline is not None else None

        pmid = self._get_text(medline.find("PMID")) if medline is not None else ""
        title = self._get_text(article_elem.find("ArticleTitle")) if article_elem is not None else ""

        journal = article_elem.find("Journal") if article_elem is not None else None
        journal_title = ""
        if journal is not None:
            journal_title = self._get_text(journal.find("ISOAbbreviation")) or self._get_text(
                journal.find("Title")
            )

        pub_date_elem = None
        if journal is not None:
            issue = journal.find("JournalIssue")
            if issue is not None:
                pub_date_elem = issue.find("PubDate")

        year = ""
        if pub_date_elem is not None:
            year = self._get_text(pub_date_elem.find("Year"))
        if not year and article_elem is not None:
            for ad in article_elem.findall("ArticleDate"):
                year = self._get_text(ad.find("Year"))
                if year:
                    break

        volume = ""
        issue_str = ""
        pages = ""
        if journal is not None:
            issue = journal.find("JournalIssue")
            if issue is not None:
                volume = self._get_text(issue.find("Volume"))
                issue_str = self._get_text(issue.find("Issue"))
        issn_print = ""
        issn_electronic = ""
        if journal is not None:
            for issn_elem in journal.findall("ISSN"):
                issn_text = self._get_text(issn_elem)
                issn_type = (issn_elem.get("IssnType") or "").lower()
                if issn_type == "print" and not issn_print:
                    issn_print = issn_text
                elif issn_type == "electronic" and not issn_electronic:
                    issn_electronic = issn_text
                elif not issn_print:
                    issn_print = issn_text
        if medline is not None and not issn_print:
            journal_info = medline.find("MedlineJournalInfo")
            if journal_info is not None:
                linking_issn = self._get_text(journal_info.find("ISSNLinking"))
                if linking_issn:
                    issn_print = linking_issn

        if article_elem is not None:
            pages = self._get_text(article_elem.find("Pagination/Page"))

        authors = []
        author_list = None
        if article_elem is not None:
            author_list = article_elem.find("AuthorList")
            if author_list is not None:
                for author in author_list.findall("Author"):
                    last = self._get_text(author.find("LastName"))
                    initials = self._get_text(author.find("Initials"))
                    if last and initials:
                        authors.append(f"{last}, {initials}")
                    elif last:
                        authors.append(last)

        keywords: List[str] = []
        if medline is not None:
            for kw_list in medline.findall("KeywordList"):
                for kw in kw_list.findall("Keyword"):
                    kw_text = self._get_text(kw)
                    if kw_text:
                        keywords.append(kw_text)
        keywords_seen = set()
        keywords_unique: List[str] = []
        for kw in keywords:
            if kw not in keywords_seen:
                keywords_seen.add(kw)
                keywords_unique.append(kw)
        keywords_str = "; ".join(keywords_unique)

        mesh_terms: List[str] = []
        if medline is not None:
            mesh_list = medline.find("MeshHeadingList")
            if mesh_list is not None:
                for mh in mesh_list.findall("MeshHeading"):
                    descriptor = self._get_text(mh.find("DescriptorName"))
                    if descriptor:
                        mesh_terms.append(descriptor)
        mesh_seen = set()
        mesh_unique: List[str] = []
        for term in mesh_terms:
            if term not in mesh_seen:
                mesh_seen.add(term)
                mesh_unique.append(term)
        mesh_terms_str = "; ".join(mesh_unique)

        abstract = ""
        if article_elem is not None:
            abstract_elem = article_elem.find("Abstract")
            if abstract_elem is not None:
                parts: List[str] = []
                for at in abstract_elem.findall("AbstractText"):
                    txt = self._get_text(at)
                    if not txt:
                        continue
                    label = at.get("Label") or at.get("NlmCategory")
                    if label:
                        parts.append(f"{label}: {txt}")
                    else:
                        parts.append(txt)
                abstract = " ".join(parts).strip()

        languages: List[str] = []
        if article_elem is not None:
            for lang in article_elem.findall("Language"):
                lang_text = self._get_text(lang)
                if lang_text:
                    languages.append(lang_text)
        lang_seen = set()
        lang_unique: List[str] = []
        for lang in languages:
            if lang not in lang_seen:
                lang_seen.add(lang)
                lang_unique.append(lang)
        language = ", ".join(lang_unique)

        article_types: List[str] = []
        if article_elem is not None:
            pub_type_list = article_elem.find("PublicationTypeList")
            if pub_type_list is not None:
                for pt in pub_type_list.findall("PublicationType"):
                    pt_text = self._get_text(pt)
                    if pt_text:
                        article_types.append(pt_text)
        type_seen = set()
        type_unique: List[str] = []
        for pt in article_types:
            if pt not in type_seen:
                type_seen.add(pt)
                type_unique.append(pt)
        article_type = "; ".join(type_unique)

        affiliations: List[str] = []
        if article_elem is not None:
            for aff_info in article_elem.findall("AffiliationInfo"):
                aff_text = self._get_text(aff_info.find("Affiliation"))
                if aff_text:
                    affiliations.append(aff_text)
        if not affiliations and author_list is not None:
            for author in author_list.findall("Author"):
                for aff_info in author.findall("AffiliationInfo"):
                    aff_text = self._get_text(aff_info.find("Affiliation"))
                    if aff_text:
                        affiliations.append(aff_text)
        aff_seen = set()
        aff_unique: List[str] = []
        for aff in affiliations:
            if aff not in aff_seen:
                aff_seen.add(aff)
                aff_unique.append(aff)
        affiliation = " | ".join(aff_unique)

        doi = ""
        pmcid = ""
        article_ids = None
        pubmed_data = article.find("PubmedData")
        if pubmed_data is not None:
            article_ids = pubmed_data.find("ArticleIdList")
        if article_ids is None and medline is not None:
            article_ids = medline.find("ArticleIdList")
        if article_ids is not None:
            for aid in article_ids.findall("ArticleId"):
                id_type = (aid.get("IdType") or "").lower()
                value = self._get_text(aid)
                if id_type == "doi" and not doi:
                    doi = value
                elif id_type == "pmc" and not pmcid:
                    pmcid = value

        first_author_last = ""
        if authors:
            first_author_last = authors[0].split(",")[0]

        cite_key = build_cite_key(first_author_last, year or "n.d.", pmid)
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

        return ArticleInfo(
            pmid=pmid,
            title=title,
            journal=journal_title,
            year=year,
            volume=volume,
            issue=issue_str,
            pages=pages,
            authors=" and ".join(authors),
            doi=doi,
            abstract=abstract,
            keywords=keywords_str,
            mesh_terms=mesh_terms_str,
            language=language,
            article_type=article_type,
            affiliation=affiliation,
            issn=issn_print,
            eissn=issn_electronic,
            url=url,
            pmcid=pmcid,
            key=cite_key,
        )


def get_default_pubmed_source() -> PubMedSource:
    return PubMedSource()
