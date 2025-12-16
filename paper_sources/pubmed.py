import datetime as _dt
from typing import List, Optional

import requests
import xml.etree.ElementTree as ET

from paper_sources import ArticleInfo, PaperSource
from services.keys import build_cite_key


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedSource(PaperSource):
    name = "pubmed"
    display_name = "PubMed"

    def search(
        self,
        query: str,
        years: int = 5,
        max_results: int = 10,
        *,
        email: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> List[ArticleInfo]:
        pmids = self._search_pubmed(query, years, max_results, email=email, api_key=api_key)
        if not pmids:
            return []

        root = self._fetch_pubmed_details(pmids, email=email, api_key=api_key)
        return [self._extract_article_info(article) for article in root.findall("PubmedArticle")]

    def _search_pubmed(
        self,
        query: str,
        years: int,
        max_results: int,
        *,
        email: Optional[str],
        api_key: Optional[str],
    ) -> List[str]:
        today = _dt.date.today()
        start_date = today.replace(year=today.year - years)
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

        resp = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        return id_list[:max_results]

    def _fetch_pubmed_details(
        self,
        pmids: List[str],
        *,
        email: Optional[str],
        api_key: Optional[str],
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

        resp = requests.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=30)
        resp.raise_for_status()
        return ET.fromstring(resp.text)

    @staticmethod
    def _get_text(elem: Optional[ET.Element]) -> str:
        return elem.text.strip() if elem is not None and elem.text else ""

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
