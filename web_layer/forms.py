from __future__ import annotations

import os
import secrets
from typing import Dict, Mapping, Tuple

from paper_sources.registry import list_sources


def get_default_years(source_name: str) -> int:
    return 5


def get_default_max_results(source_name: str) -> int:
    return 5


def generate_random_email() -> str:
    local_part = f"user_{secrets.token_hex(4)}"
    domain = os.environ.get("DEFAULT_EMAIL_DOMAIN") or "example.com"
    return f"{local_part}@{domain}"


def get_default_email(source_name: str) -> str:
    return ""


def get_default_api_key(source_name: str) -> str:
    return ""


def get_source_defaults(source_name: str) -> Dict[str, str | int]:
    return {
        "years": get_default_years(source_name),
        "max_results": get_default_max_results(source_name),
        "email": get_default_email(source_name),
        "api_key": get_default_api_key(source_name),
        "output": "pubmed_results.bib",
    }


def default_source_name() -> str:
    sources = list_sources()
    return sources[0].name if sources else ""


def default_ai_provider_name() -> str:
    return "openai"


def default_query(source_name: str) -> str:
    return '"artificial intelligence" AND ("dental implants" OR "implant dentistry" OR "oral implantology")'


def parse_int(value: str, default_value: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default_value


def parse_float(value: str, default_value: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default_value


def resolve_form(form_data: Mapping[str, str]) -> Tuple[Dict[str, str], Dict[str, object]]:
    """返回渲染用的表单值以及用于搜索的解析结果。"""

    source = (form_data.get("source") or default_source_name()).strip()
    defaults = get_source_defaults(source)

    ai_provider = (form_data.get("ai_provider") or default_ai_provider_name()).strip()
    query = (form_data.get("query") or default_query(source)).strip()
    years_raw = (form_data.get("years") or "").strip()
    max_results_raw = (form_data.get("max_results") or "").strip()
    email_raw = (form_data.get("email") or "").strip()
    api_key_raw = (form_data.get("api_key") or "").strip()
    output_raw = (form_data.get("output") or "").strip()
    gemini_api_key_raw = (form_data.get("gemini_api_key") or "").strip()
    gemini_model_raw = (form_data.get("gemini_model") or "").strip()
    gemini_temperature_raw = (form_data.get("gemini_temperature") or "").strip()
    openai_api_key_raw = (form_data.get("openai_api_key") or "").strip()
    openai_base_url_raw = (form_data.get("openai_base_url") or "").strip()
    openai_model_raw = (form_data.get("openai_model") or "").strip()
    openai_temperature_raw = (form_data.get("openai_temperature") or "").strip()
    ollama_api_key_raw = (form_data.get("ollama_api_key") or "").strip()
    ollama_base_url_raw = (form_data.get("ollama_base_url") or "").strip()
    ollama_model_raw = (form_data.get("ollama_model") or "").strip()
    ollama_temperature_raw = (form_data.get("ollama_temperature") or "").strip()

    if email_raw:
        resolved_email = email_raw
    elif defaults["email"]:
        resolved_email = str(defaults["email"])
    else:
        resolved_email = generate_random_email()

    resolved_output = output_raw or str(defaults["output"])
    resolved_gemini_temperature = parse_float(gemini_temperature_raw, 0.0)

    resolved = {
        "source": source,
        "ai_provider": ai_provider,
        "query": query,
        "years": parse_int(years_raw, int(defaults["years"])),
        "max_results": parse_int(max_results_raw, int(defaults["max_results"])),
        "email": resolved_email,
        "api_key": api_key_raw or str(defaults["api_key"]),
        "output": resolved_output,
        "gemini_api_key": gemini_api_key_raw,
        "gemini_model": gemini_model_raw,
        "gemini_temperature": resolved_gemini_temperature,
        "openai_api_key": openai_api_key_raw,
        "openai_base_url": openai_base_url_raw,
        "openai_model": openai_model_raw,
        "openai_temperature": parse_float(openai_temperature_raw, 0.0),
        "ollama_api_key": ollama_api_key_raw,
        "ollama_base_url": ollama_base_url_raw,
        "ollama_model": ollama_model_raw,
        "ollama_temperature": parse_float(ollama_temperature_raw, 0.0),
    }

    form = {
        "source": source,
        "ai_provider": ai_provider,
        "query": query,
        "years": years_raw,
        "max_results": max_results_raw,
        "email": email_raw,
        "api_key": api_key_raw,
        "output": output_raw,
        "gemini_api_key": gemini_api_key_raw,
        "gemini_model": gemini_model_raw,
        "gemini_temperature": gemini_temperature_raw,
        "openai_api_key": openai_api_key_raw,
        "openai_base_url": openai_base_url_raw,
        "openai_model": openai_model_raw,
        "openai_temperature": openai_temperature_raw,
        "ollama_api_key": ollama_api_key_raw,
        "ollama_base_url": ollama_base_url_raw,
        "ollama_model": ollama_model_raw,
        "ollama_temperature": ollama_temperature_raw,
    }

    return form, resolved

