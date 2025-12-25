from typing import Dict, List, Optional, Type

from .base import AiProvider
from .gemini import GeminiProvider
from .openai_provider import OpenAIProvider


_PROVIDER_ORDER: List[Type[AiProvider]] = [OpenAIProvider, GeminiProvider]
_PROVIDER_TYPES: Dict[str, Type[AiProvider]] = {provider.name: provider for provider in _PROVIDER_ORDER}


def get_provider(name: str) -> Optional[AiProvider]:
    provider_cls = _PROVIDER_TYPES.get(name)
    if not provider_cls:
        return None
    return provider_cls()


def list_providers() -> List[AiProvider]:
    return [provider_cls() for provider_cls in _PROVIDER_ORDER]
