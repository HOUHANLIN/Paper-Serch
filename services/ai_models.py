from __future__ import annotations

import json
import subprocess
from typing import Dict, List, Tuple

from ai_providers.gemini import GeminiProvider
from ai_providers.ollama import OllamaProvider
from ai_providers.openai_provider import OpenAIProvider


def _normalize_openai_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return "https://api.openai.com/v1"
    if url.endswith("/models"):
        url = url[: -len("/models")].rstrip("/")
    if url.endswith("/v1") or url.endswith("/api/v3") or url.endswith("/v1beta"):
        return url
    return url + "/v1"


def _run_curl_json(url: str, headers: Dict[str, str] | None = None, timeout_seconds: int = 8) -> Tuple[bool, object, str]:
    args: List[str] = ["curl", "-sS", "--max-time", str(timeout_seconds)]
    if headers:
        for k, v in headers.items():
            args.extend(["-H", f"{k}: {v}"])
    args.append(url)
    try:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)  # nosec - local tool
    except Exception as exc:  # pylint: disable=broad-except
        return False, {}, f"curl 执行失败：{exc}"

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return False, {}, f"curl 返回异常（code={proc.returncode}）：{stderr or '未知错误'}"

    raw = (proc.stdout or "").strip()
    if not raw:
        return False, {}, "curl 返回空响应"
    try:
        return True, json.loads(raw), ""
    except Exception as exc:  # pylint: disable=broad-except
        preview = raw[:2000]
        return False, {}, f"解析 JSON 失败：{exc}，响应前 2k：{preview}"


def _extract_ids_from_openai_models(payload: object) -> List[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        ids = []
        for item in data:
            if isinstance(item, dict):
                mid = item.get("id")
                if isinstance(mid, str) and mid.strip():
                    ids.append(mid.strip())
        return ids
    return []


def list_openai_models(
    *,
    api_key: str,
    base_url: str,
) -> Tuple[List[str], str]:
    resolved_key = (api_key or OpenAIProvider().api_key or "").strip()
    resolved_base = _normalize_openai_base_url((base_url or OpenAIProvider().base_url or "").strip())
    if not resolved_key:
        return [], "未配置 OpenAI API Key"

    ok, payload, err = _run_curl_json(
        f"{resolved_base}/models",
        headers={"Authorization": f"Bearer {resolved_key}"},
    )
    if not ok:
        return [], err
    models = sorted(set(_extract_ids_from_openai_models(payload)))
    if not models:
        return [], "未从接口解析到可用模型"
    return models, f"获取到 {len(models)} 个模型"


def list_ollama_models(
    *,
    api_key: str,
    base_url: str,
) -> Tuple[List[str], str]:
    defaults = OllamaProvider()
    resolved_key = (api_key or defaults.api_key or "ollama").strip()
    resolved_base = _normalize_openai_base_url((base_url or defaults.base_url or "").strip())

    ok, payload, err = _run_curl_json(
        f"{resolved_base}/models",
        headers={"Authorization": f"Bearer {resolved_key}"},
    )
    if ok:
        models = sorted(set(_extract_ids_from_openai_models(payload)))
        if models:
            return models, f"获取到 {len(models)} 个模型"

    # Fallback to Ollama native endpoint: /api/tags (base without /v1)
    root = resolved_base[:-3] if resolved_base.endswith("/v1") else resolved_base
    ok2, payload2, err2 = _run_curl_json(f"{root}/api/tags")
    if not ok2:
        return [], err or err2
    if isinstance(payload2, dict) and isinstance(payload2.get("models"), list):
        names = []
        for item in payload2["models"]:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
        models = sorted(set(names))
        if models:
            return models, f"获取到 {len(models)} 个模型"
    return [], "未从接口解析到可用模型"


def list_gemini_models(
    *,
    api_key: str,
) -> Tuple[List[str], str]:
    resolved_key = (api_key or GeminiProvider().api_key or "").strip()
    if not resolved_key:
        return [], "未配置 Gemini API Key"
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={resolved_key}"
    ok, payload, err = _run_curl_json(url)
    if not ok:
        return [], err
    models: List[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("models"), list):
        for item in payload["models"]:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                # name is like "models/gemini-2.0-flash"
                models.append(name.strip().split("/")[-1])
    models = sorted(set(m for m in models if m))
    if not models:
        return [], "未从接口解析到可用模型"
    return models, f"获取到 {len(models)} 个模型"
