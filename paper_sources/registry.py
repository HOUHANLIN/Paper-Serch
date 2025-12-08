from typing import Dict, List, Optional

from .base import PaperSource
from .embase import EmbaseSource
from .pubmed import PubMedSource

_SOURCES: Dict[str, PaperSource] = {
    PubMedSource.name: PubMedSource(),
    EmbaseSource.name: EmbaseSource(),
}


def get_source(name: str) -> Optional[PaperSource]:
    return _SOURCES.get(name)


def list_sources() -> List[PaperSource]:
    return list(_SOURCES.values())
