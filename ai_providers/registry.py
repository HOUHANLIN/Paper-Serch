from typing import Dict, List, Optional

from .base import AiProvider, NoopAiProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai_provider import OpenAIProvider


def _build_registry() -> Dict[str, AiProvider]:
    registry: Dict[str, AiProvider] = {NoopAiProvider.name: NoopAiProvider()}
    registry[GeminiProvider.name] = GeminiProvider()
    registry[OllamaProvider.name] = OllamaProvider()
    registry[OpenAIProvider.name] = OpenAIProvider()
    return registry


_AI_PROVIDERS = _build_registry()


def get_provider(name: str) -> Optional[AiProvider]:
    return _AI_PROVIDERS.get(name)


def list_providers() -> List[AiProvider]:
    return list(_AI_PROVIDERS.values())
