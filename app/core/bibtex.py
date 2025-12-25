import textwrap
from typing import Iterable, List, Tuple

from app.sources import ArticleInfo


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


def article_to_bibtex(info: ArticleInfo) -> str:
    fields = {
        "author": info.authors,
        "title": info.title,
        "journal": info.journal,
        "year": info.year,
        "volume": info.volume,
        "number": info.issue,
        "pages": info.pages,
        "doi": info.doi,
        "pmid": info.pmid,
        "abstract": info.abstract,
        "keywords": info.keywords,
        "mesh_terms": info.mesh_terms,
        "language": info.language,
        "article_type": info.article_type,
        "affiliation": info.affiliation,
        "issn": info.issn,
        "eissn": info.eissn,
        "url": info.url,
        "pmcid": info.pmcid,
        "annote": info.annote,
    }

    lines = [f"@article{{{_escape_bibtex(info.key or 'unknown')},"]
    for k, v in fields.items():
        if not v:
            continue
        if k == "annote":
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


def build_bibtex_entries(infos: Iterable[ArticleInfo]) -> Tuple[str, int]:
    entries: List[str] = []
    for info in infos:
        entries.append(article_to_bibtex(info))
    return "\n\n".join(entries), len(entries)
