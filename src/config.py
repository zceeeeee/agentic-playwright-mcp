"""
Configuration loader for agentic-playwright-mcp.

Loads environment variables from .env and provides typed access
to configuration values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Locate and load .env from project root (two levels up from this file)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.is_file():
    load_dotenv(_ENV_FILE, override=False)

# ---------------------------------------------------------------------------
# Well-known keys with optional defaults
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, str] = {
    "PLAYWRIGHT_DOWNLOAD_HOST": "",
    "BROWSER_HEADLESS": "false",
    "USE_CLOAKBROWSER": "true",
    "DOMAIN_DIR": str(_PROJECT_ROOT / "domains"),
    "LOG_LEVEL": "INFO",
    "LOG_FORMAT": "text",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MODEL": "gpt-4o-mini",
    "EXPLORE_MAX_RETRIES": "3",
    "EXPLORE_ACTION_TIMEOUT": "15000",
    "EXPLORE_SNAPSHOT_MAX_ELEMENTS": "50",
    "EXPERIENCE_STORAGE_DIR": str(_PROJECT_ROOT / "data" / "explore_experiences"),
    "EXPERIENCE_UPGRADE_THRESHOLD": "3",
    "EXPERIENCE_CONFIDENCE_THRESHOLD": "0.8",
    "LLM_THINKING_ENABLED": "true",
}


def get_config() -> dict[str, Any]:
    """Return a merged configuration dict (env vars + defaults)."""
    config: dict[str, Any] = {}
    for key, default in _DEFAULTS.items():
        config[key] = os.getenv(key, default)
    # Include API keys only if set (do not expose defaults for secrets)
    for secret_key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        val = os.getenv(secret_key)
        if val:
            config[secret_key] = val
    return config


def get_api_key(key_name: str) -> str:
    """Return the value of *key_name* from the environment.

    Raises ``ValueError`` when the key is missing or empty.
    """
    value = os.getenv(key_name, "").strip()
    if not value:
        raise ValueError(
            f"API key '{key_name}' is not set. "
            f"Add it to {_ENV_FILE} or export it as an environment variable."
        )
    return value
