"""Persists a runtime configuration value to .env and the in-process config module.

The single place that writes a config change — whether from the
Settings dialog (a human choice) or GeminiProvider's automatic model
discovery/self-healing (a system choice) — so it is immediately
reflected in config.* (no restart needed) and durable across restarts,
without duplicating this logic in multiple places.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import set_key

import config

_DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env"


def set_config_value(key: str, value: str, env_path: Optional[Path] = None) -> None:
    """Write `key=value` to .env, os.environ, and config.<key>.

    `env_path` is overridable so tests never touch the real project
    .env file.
    """

    target_path = env_path if env_path is not None else _DEFAULT_ENV_PATH

    set_key(str(target_path), key, value)
    os.environ[key] = value
    setattr(config, key, value)
