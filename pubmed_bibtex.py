import os
import sys

from ai_providers.registry import get_provider
from paper_sources.registry import get_source
from services.bibtex import build_bibtex_entries
from services.env_loader import get_env_int, load_env


def main() -> int:
    load_env()

    source_name = (os.environ.get("PAPER_SOURCE") or "pubmed").lower()
    source = get_source(source_name)
    if not source:
        print(f"Error: unsupported source '{source_name}'.", file=sys.stderr)
        return 1

    env_prefix = source_name.upper()
    query = (
        os.environ.get(f"{env_prefix}_QUERY")
        or os.environ.get("QUERY")
        or os.environ.get("PUBMED_QUERY")
    )
    if not query:
        print(
            "Error: no query provided. Set QUERY or *_QUERY in .env.",
            file=sys.stderr,
        )
        return 1

    years = get_env_int(f"{env_prefix}_YEARS", get_env_int("PUBMED_YEARS", 5))
    max_results = get_env_int(
        f"{env_prefix}_MAX_RESULTS", get_env_int("PUBMED_MAX_RESULTS", 10)
    )
    output_path = (
        os.environ.get(f"{env_prefix}_OUTPUT")
        or os.environ.get("PUBMED_OUTPUT")
        or "pubmed_results.bib"
    )

    email = os.environ.get(f"{env_prefix}_EMAIL") or os.environ.get("PUBMED_EMAIL")
    api_key = (
        os.environ.get(f"{env_prefix}_API_KEY")
        or os.environ.get("PUBMED_API_KEY")
        or os.environ.get("NCBI_API_KEY")
    )
    if api_key and api_key.strip() == "your_ncbi_api_key_here":
        api_key = None

    extra_params = {}
    if source_name == "embase":
        insttoken = os.environ.get("EMBASE_INSTTOKEN") or os.environ.get("ELS_INSTTOKEN")
        if insttoken:
            extra_params["insttoken"] = insttoken

    provider = get_provider(os.environ.get("AI_PROVIDER", "none"))

    try:
        articles = source.search(
            query=query,
            years=years,
            max_results=max_results,
            email=email,
            api_key=api_key,
            **extra_params,
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
