from typing import Iterable


def build_cite_key(*parts: Iterable[str]) -> str:
    flat_parts = []
    for part in parts:
        if isinstance(part, str):
            value = part.strip()
            if value:
                flat_parts.append(value)
        else:
            try:
                value = str(part).strip()
                if value:
                    flat_parts.append(value)
            except Exception:
                continue
    return "_".join(flat_parts) if flat_parts else "citation"
