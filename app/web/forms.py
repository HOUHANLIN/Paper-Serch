from __future__ import annotations

import os
import secrets
from typing import Dict, Mapping, Optional, Tuple

from app.sources.registry import list_sources


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


def resolve_form(
    form_data: Mapping[str, str],
    *,
    allow_ai_customization: bool = True,
    preset_ai_config: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Dict[str, object]]:
    """返回渲染用的表单值以及用于搜索的解析结果。"""

    preset_ai_config = preset_ai_config or {}

    def _effective(raw: str, key: str) -> str:
        base = (raw or "").strip()
        if allow_ai_customization:
            return base or str(preset_ai_config.get(key) or "")
        return str(preset_ai_config.get(key) or "")

    source = (form_data.get("source") or default_source_name()).strip()
    defaults = get_source_defaults(source)

    ai_provider = _effective(form_data.get("ai_provider") or "", "ai_provider") or default_ai_provider_name()
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
        "gemini_api_key": _effective(gemini_api_key_raw, "gemini_api_key"),
        "gemini_model": _effective(gemini_model_raw, "gemini_model"),
        "gemini_temperature": parse_float(_effective(gemini_temperature_raw, "gemini_temperature"), resolved_gemini_temperature),
        "openai_api_key": _effective(openai_api_key_raw, "openai_api_key"),
        "openai_base_url": _effective(openai_base_url_raw, "openai_base_url"),
        "openai_model": _effective(openai_model_raw, "openai_model"),
        "openai_temperature": parse_float(_effective(openai_temperature_raw, "openai_temperature"), 0.0),
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
    }

    return form, resolved
