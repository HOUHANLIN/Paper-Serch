import os
from typing import Optional


def load_env(path: str = ".env") -> None:
    """Read simple KEY=VALUE pairs from a .env file into os.environ."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        return


def get_env_int(key: str, default: int) -> int:
    raw: Optional[str] = os.environ.get(key)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default
