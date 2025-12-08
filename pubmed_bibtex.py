import argparse
import datetime as _dt
import os
import sys
import textwrap
from typing import Dict, List, Optional

import requests
import xml.etree.ElementTree as ET


EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _load_env(path: str = ".env") -> None:
    """从 .env 文件中读取简单的 KEY=VALUE 键值对并写入 os.environ。"""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        # If the file can't be read, just skip silently.
        return


def search_pubmed(
    query: str,
    years: int = 5,
    max_results: int = 10,
    email: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[str]:
    """在 PubMed 上执行检索并返回 PMID 列表。"""
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


def fetch_pubmed_details(
    pmids: List[str],
    email: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ET.Element:
    """根据 PMID 列表从 PubMed 获取文献信息，返回 XML 根节点。"""
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


def _get_text(elem: Optional[ET.Element]) -> str:
    return elem.text.strip() if elem is not None and elem.text else ""


def _init_gemini_client():
    """初始化 Gemini 客户端；若未配置则返回占位的空值。"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, None, None
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except Exception as exc:  # pragma: no cover - 环境依赖问题
        print(
            f"警告: 导入 google-genai 失败，将跳过 AI 总结: {exc}",
            file=sys.stderr,
        )
        return None, None, None

    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:  # pragma: no cover - 运行时配置问题
        print(
            f"警告: 初始化 Gemini 客户端失败，将跳过 AI 总结: {exc}",
            file=sys.stderr,
        )
        return None, None, None

    # 模型名称从环境变量读取，避免在脚本中写死配置
    model = os.environ.get("GEMINI_MODEL")
    if not model:
        print(
            "警告: 未设置 GEMINI_MODEL 环境变量，将跳过 AI 总结。",
            file=sys.stderr,
        )
        return None, None, None

    return client, model, types


def _summarize_with_gemini(
    client,
    model: str,
    types,
    info: Dict[str, str],
) -> str:
    """使用 Gemini 基于标题和摘要生成结构化 JSON 总结."""
    abstract = (info.get("abstract") or "").strip()
    if not abstract:
        return ""

    title = (info.get("title") or "").strip()
    journal = (info.get("journal") or "").strip()
    year = (info.get("year") or "").strip()

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
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            )
        ]
        # 温度可配置，默认温度为 0
        temperature_str = os.environ.get("GEMINI_TEMPERATURE", "0")
        try:
            temperature = float(temperature_str)
        except ValueError:
            temperature = 0.0

        config = types.GenerateContentConfig(temperature=temperature)

        chunks: List[str] = []
        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            text = getattr(chunk, "text", "") or ""
            if text:
                chunks.append(text)
        return " ".join(chunks).strip()
    except Exception as exc:  # pragma: no cover - 外部服务错误
        print(
            f"警告: 生成 AI 总结失败（PMID {info.get('pmid', '')}）: {exc}",
            file=sys.stderr,
        )
        return ""


def _extract_article_info(article: ET.Element) -> Dict[str, str]:
    medline = article.find("MedlineCitation")
    article_elem = medline.find("Article") if medline is not None else None

    pmid = _get_text(medline.find("PMID")) if medline is not None else ""
    title = _get_text(article_elem.find("ArticleTitle")) if article_elem is not None else ""

    journal = article_elem.find("Journal") if article_elem is not None else None
    journal_title = ""
    if journal is not None:
        journal_title = _get_text(journal.find("ISOAbbreviation")) or _get_text(
            journal.find("Title")
        )

    pub_date_elem = None
    if journal is not None:
        issue = journal.find("JournalIssue")
        if issue is not None:
            pub_date_elem = issue.find("PubDate")

    year = ""
    if pub_date_elem is not None:
        year = _get_text(pub_date_elem.find("Year"))
    if not year:
        # 回退策略：若无 Year 字段则尝试使用 ArticleDate 中的年份
        if article_elem is not None:
            for ad in article_elem.findall("ArticleDate"):
                year = _get_text(ad.find("Year"))
                if year:
                    break

    volume = ""
    issue_str = ""
    pages = ""
    if journal is not None:
        issue = journal.find("JournalIssue")
        if issue is not None:
            volume = _get_text(issue.find("Volume"))
            issue_str = _get_text(issue.find("Issue"))
    issn_print = ""
    issn_electronic = ""
    if journal is not None:
        for issn_elem in journal.findall("ISSN"):
            issn_text = _get_text(issn_elem)
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
            linking_issn = _get_text(journal_info.find("ISSNLinking"))
            if linking_issn:
                issn_print = linking_issn

    if article_elem is not None:
        pages = _get_text(article_elem.find("Pagination/Page"))

    authors = []
    author_list = None
    if article_elem is not None:
        author_list = article_elem.find("AuthorList")
        if author_list is not None:
            for author in author_list.findall("Author"):
                last = _get_text(author.find("LastName"))
                initials = _get_text(author.find("Initials"))
                if last and initials:
                    authors.append(f"{last}, {initials}")
                elif last:
                    authors.append(last)

    # 关键词
    keywords: List[str] = []
    if medline is not None:
        for kw_list in medline.findall("KeywordList"):
            for kw in kw_list.findall("Keyword"):
                kw_text = _get_text(kw)
                if kw_text:
                    keywords.append(kw_text)
    # 去重并保持原有顺序
    keywords_seen = set()
    keywords_unique: List[str] = []
    for kw in keywords:
        if kw not in keywords_seen:
            keywords_seen.add(kw)
            keywords_unique.append(kw)
    keywords_str = "; ".join(keywords_unique)

    # MeSH 主题词
    mesh_terms: List[str] = []
    if medline is not None:
        mesh_list = medline.find("MeshHeadingList")
        if mesh_list is not None:
            for mh in mesh_list.findall("MeshHeading"):
                descriptor = _get_text(mh.find("DescriptorName"))
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
                txt = _get_text(at)
                if not txt:
                    continue
                label = at.get("Label") or at.get("NlmCategory")
                if label:
                    parts.append(f"{label}: {txt}")
                else:
                    parts.append(txt)
            abstract = " ".join(parts).strip()

    # 文章语言
    languages: List[str] = []
    if article_elem is not None:
        for lang in article_elem.findall("Language"):
            lang_text = _get_text(lang)
            if lang_text:
                languages.append(lang_text)
    lang_seen = set()
    lang_unique: List[str] = []
    for lang in languages:
        if lang not in lang_seen:
            lang_seen.add(lang)
            lang_unique.append(lang)
    language = ", ".join(lang_unique)

    # 文献类型
    article_types: List[str] = []
    if article_elem is not None:
        pub_type_list = article_elem.find("PublicationTypeList")
        if pub_type_list is not None:
            for pt in pub_type_list.findall("PublicationType"):
                pt_text = _get_text(pt)
                if pt_text:
                    article_types.append(pt_text)
    type_seen = set()
    type_unique: List[str] = []
    for pt in article_types:
        if pt not in type_seen:
            type_seen.add(pt)
            type_unique.append(pt)
    article_type = "; ".join(type_unique)

    # 作者单位信息
    affiliations: List[str] = []
    if article_elem is not None:
        for aff_info in article_elem.findall("AffiliationInfo"):
            aff_text = _get_text(aff_info.find("Affiliation"))
            if aff_text:
                affiliations.append(aff_text)
    if not affiliations and author_list is not None:
        for author in author_list.findall("Author"):
            for aff_info in author.findall("AffiliationInfo"):
                aff_text = _get_text(aff_info.find("Affiliation"))
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
            value = _get_text(aid)
            if id_type == "doi" and not doi:
                doi = value
            elif id_type == "pmc" and not pmcid:
                pmcid = value

    first_author_last = ""
    if authors:
        first_author_last = authors[0].split(",")[0]

    year_for_key = year or "n.d."
    key_parts = [p for p in [first_author_last, year_for_key, pmid] if p]
    cite_key = "_".join(key_parts) if key_parts else f"pmid_{pmid or 'unknown'}"

    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""

    return {
        "pmid": pmid,
        "title": title,
        "journal": journal_title,
        "year": year,
        "volume": volume,
        "issue": issue_str,
        "pages": pages,
        "authors": " and ".join(authors),
        "doi": doi,
        "abstract": abstract,
        "keywords": keywords_str,
        "mesh_terms": mesh_terms_str,
        "language": language,
        "article_type": article_type,
        "affiliation": affiliation,
        "issn": issn_print,
        "eissn": issn_electronic,
        "url": url,
        "pmcid": pmcid,
        "annote": "",
        "key": cite_key,
    }


def _escape_bibtex(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "\\": "\\\\",
        "{": "\\{",
        "}": "\\}",
        "%": "\\%",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def article_to_bibtex(info: Dict[str, str]) -> str:
    fields = {
        "author": info.get("authors", ""),
        "title": info.get("title", ""),
        "journal": info.get("journal", ""),
        "year": info.get("year", ""),
        "volume": info.get("volume", ""),
        "number": info.get("issue", ""),
        "pages": info.get("pages", ""),
        "doi": info.get("doi", ""),
        "pmid": info.get("pmid", ""),
        "abstract": info.get("abstract", ""),
        "keywords": info.get("keywords", ""),
        "mesh_terms": info.get("mesh_terms", ""),
        "language": info.get("language", ""),
        "article_type": info.get("article_type", ""),
        "affiliation": info.get("affiliation", ""),
        "issn": info.get("issn", ""),
        "eissn": info.get("eissn", ""),
        "url": info.get("url", ""),
        "pmcid": info.get("pmcid", ""),
        # annote 字段用于保存 JSON 字符串，这里不进行转义和换行包装
        "annote": info.get("annote", ""),
    }

    lines = [f"@article{{{_escape_bibtex(info.get('key', 'unknown'))},"]
    for k, v in fields.items():
        if not v:
            continue
        if k == "annote":
            # 直接写入原始 JSON，避免破坏结构
            lines.append(f"  {k} = {{{v}}},")
            continue
        wrapped = textwrap.fill(
            _escape_bibtex(v),
            width=78,
            subsequent_indent=" " * (len(k) + 5),
        )
        lines.append(f"  {k} = {{{wrapped}}},")
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)


def build_bibtex_entries(
    root: ET.Element,
):
    """根据 PubMed XML 根节点构建 BibTeX 文本和条目信息。

    返回值:
        (bibtex_text, count, infos)
    """
    articles = root.findall("PubmedArticle")
    client, gemini_model, genai_types = _init_gemini_client()
    use_gemini = client is not None and gemini_model is not None and genai_types is not None

    entries: List[str] = []
    infos: List[Dict[str, str]] = []
    for article in articles:
        info = _extract_article_info(article)
        if use_gemini:
            summary = _summarize_with_gemini(
                client,
                gemini_model,
                genai_types,
                info,
            )
            if summary:
                info["annote"] = summary
        infos.append(info)
        entries.append(article_to_bibtex(info))

    return "\n\n".join(entries), len(entries), infos


def write_bibtex_file(
    root: ET.Element,
    output_path: str,
) -> int:
    bibtex_text, count, _ = build_bibtex_entries(root)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(bibtex_text)

    return count


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search PubMed for recent articles and export as BibTeX.",
    )
    parser.add_argument(
        "--query",
        "-q",
        help="Search keywords for PubMed.",
    )
    parser.add_argument(
        "--years",
        "-y",
        type=int,
        default=None,
        help="How many years back to search (default: 5, or PUBMED_YEARS in .env).",
    )
    parser.add_argument(
        "--max-results",
        "-n",
        type=int,
        default=None,
        help="Maximum number of articles to retrieve (default: 10, or PUBMED_MAX_RESULTS in .env).",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output .bib file path (default: pubmed_results.bib, or PUBMED_OUTPUT in .env).",
    )
    parser.add_argument(
        "--email",
        help="Contact email for NCBI E-utilities (recommended).",
    )
    parser.add_argument(
        "--api-key",
        help="NCBI API key for higher rate limits (optional).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    _load_env()
    args = parse_args(argv)

    query = args.query or os.environ.get("PUBMED_QUERY") or os.environ.get("QUERY")
    if not query:
        print(
            "Error: no query provided. "
            "Set PUBMED_QUERY in .env or use --query.",
            file=sys.stderr,
        )
        return 1

    years_env = os.environ.get("PUBMED_YEARS")
    max_results_env = os.environ.get("PUBMED_MAX_RESULTS")
    output_env = os.environ.get("PUBMED_OUTPUT")

    years = args.years if args.years is not None else int(years_env or "5")
    max_results = (
        args.max_results if args.max_results is not None else int(max_results_env or "10")
    )
    output_path = args.output or output_env or "pubmed_results.bib"

    email = args.email or os.environ.get("PUBMED_EMAIL")
    api_key = (
        args.api_key
        or os.environ.get("PUBMED_API_KEY")
        or os.environ.get("NCBI_API_KEY")
    )
    # 若仍然是示例中的占位符，则视为未配置 API Key
    if api_key and api_key.strip() == "your_ncbi_api_key_here":
        api_key = None

    try:
        pmids = search_pubmed(
            query=query,
            years=years,
            max_results=max_results,
            email=email,
            api_key=api_key,
        )
        if not pmids:
            print("No results found for the given query and time range.")
            return 0

        xml_root = fetch_pubmed_details(
            pmids,
            email=email,
            api_key=api_key,
        )
        count = write_bibtex_file(xml_root, output_path)
        print(f"Wrote {count} BibTeX entries to {output_path}")
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
