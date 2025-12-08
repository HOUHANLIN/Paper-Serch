import argparse
import os
import sys
from typing import List, Optional

from ai_providers.registry import get_provider
from paper_sources.pubmed import PubMedSource
from services.bibtex import build_bibtex_entries
from services.env_loader import get_env_int, load_env


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search PubMed for recent articles and export as BibTeX.",
    )
    parser.add_argument("--query", "-q", help="Search keywords for PubMed.")
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
    parser.add_argument("--email", help="Contact email for NCBI E-utilities (recommended).")
    parser.add_argument("--api-key", help="NCBI API key for higher rate limits (optional).")
    parser.add_argument(
        "--ai-provider",
        default=os.environ.get("AI_PROVIDER", "none"),
        help="AI provider name for summaries (default: none).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    load_env()
    args = parse_args(argv)

    query = args.query or os.environ.get("PUBMED_QUERY") or os.environ.get("QUERY")
    if not query:
        print(
            "Error: no query provided. Set PUBMED_QUERY in .env or use --query.",
            file=sys.stderr,
        )
        return 1

    years = args.years if args.years is not None else get_env_int("PUBMED_YEARS", 5)
    max_results = (
        args.max_results if args.max_results is not None else get_env_int("PUBMED_MAX_RESULTS", 10)
    )
    output_path = args.output or os.environ.get("PUBMED_OUTPUT") or "pubmed_results.bib"

    email = args.email or os.environ.get("PUBMED_EMAIL")
    api_key = (
        args.api_key
        or os.environ.get("PUBMED_API_KEY")
        or os.environ.get("NCBI_API_KEY")
    )
    if api_key and api_key.strip() == "your_ncbi_api_key_here":
        api_key = None

    source = PubMedSource()
    provider = get_provider(args.ai_provider or "none")

    try:
        articles = source.search(
            query=query,
            years=years,
            max_results=max_results,
            email=email,
            api_key=api_key,
        )
        if not articles:
            print("No results found for the given query and time range.")
            return 0

        if provider and provider.name != "none":
            for info in articles:
                summary = provider.summarize(info)
                if summary:
                    info.annote = summary

        bibtex_text, count = build_bibtex_entries(articles)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(bibtex_text)
        print(f"Wrote {count} BibTeX entries to {output_path}")
        return 0
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
