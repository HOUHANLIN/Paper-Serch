from typing import Dict, List, Optional

from .base import AiProvider, NoopAiProvider
from .gemini import GeminiProvider, get_default_gemini_provider
from .openai_provider import OpenAIProvider


def _build_registry() -> Dict[str, AiProvider]:
    registry: Dict[str, AiProvider] = {NoopAiProvider.name: NoopAiProvider()}

    gemini = get_default_gemini_provider()
    if gemini:
        registry[GeminiProvider.name] = gemini

    # 提前占位 OpenAI，便于后续扩展
    registry[OpenAIProvider.name] = OpenAIProvider()
    return registry


_AI_PROVIDERS = _build_registry()


def get_provider(name: str) -> Optional[AiProvider]:
    return _AI_PROVIDERS.get(name)


def list_providers() -> List[AiProvider]:
    return list(_AI_PROVIDERS.values())
