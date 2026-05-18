"""Tiny .env loader — zero deps. Local-debug only.

Reads `fetch_data/.env.local` (gitignored) and populates `os.environ` for any
key not already set. Real env (GitHub Actions secrets) always wins.

Format: `KEY=value` per line. `#` comments and blank lines OK. Quotes around
the value are stripped. No interpolation, no multi-line values.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env_local(path: str | os.PathLike | None = None) -> int:
    """Load env file. Returns number of keys set."""
    p = Path(path) if path else Path(__file__).parent / ".env.local"
    if not p.is_file():
        return 0
    count = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val
            count += 1
    return count
