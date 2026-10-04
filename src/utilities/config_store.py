"""Global ``mr`` behavior defaults (portable across repos, not branch names).

Stores ``key=value`` lines at ``${XDG_CONFIG_HOME:-~/.config}/mr/config``.
Known keys:

- ``merge.strategy``: ``squash`` (default) | ``merge``
- ``merge.push``: ``auto`` (default) | ``always`` | ``never``

``auto`` push means: push the base after merging iff the stored base parses
as ``<known-remote>/<branch>`` (e.g. ``origin/main`` pushes, ``main`` does not).
"""

from __future__ import annotations

import os
from pathlib import Path

STRATEGY_KEY = "merge.strategy"
PUSH_KEY = "merge.push"

STRATEGIES = ("squash", "merge")
PUSH_MODES = ("auto", "always", "never")

DEFAULTS = {
    STRATEGY_KEY: "squash",
    PUSH_KEY: "auto",
}

ALLOWED: dict[str, tuple[str, ...]] = {
    STRATEGY_KEY: STRATEGIES,
    PUSH_KEY: PUSH_MODES,
}


class ConfigError(RuntimeError):
    """Raised for invalid keys/values."""


def config_file_path() -> Path:
    """Absolute path of the global config file (env-aware, testable)."""
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        base = Path(xdg)
    else:
        base = Path.home() / ".config"
    return base / "mr" / "config"


def read_config() -> dict[str, str]:
    """All ``key=value`` pairs; corrupt lines and unknown keys are ignored."""
    path = config_file_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if key in ALLOWED and value in ALLOWED[key]:
            values[key] = value
    return values


def get(key: str, default: str) -> str:
    """Value for *key* or *default* when unset/invalid."""
    return read_config().get(key, default)


def get_merge_strategy() -> str:
    """``squash`` or ``merge`` (defaults to ``squash``)."""
    return get(STRATEGY_KEY, DEFAULTS[STRATEGY_KEY])


def get_merge_push() -> str:
    """``auto`` | ``always`` | ``never`` (defaults to ``auto``)."""
    return get(PUSH_KEY, DEFAULTS[PUSH_KEY])


def set_value(key: str, value: str) -> str:
    """Validate, persist, and return ``value``. Raises ConfigError on misuse."""
    if key not in ALLOWED:
        raise ConfigError(f"unknown config key '{key}' (known: merge.strategy, merge.push)")
    if value not in ALLOWED[key]:
        allowed = "|".join(ALLOWED[key])
        raise ConfigError(f"invalid value '{value}' for '{key}' (expected {allowed})")
    values = read_config()
    values[key] = value
    path = config_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={values[k]}\n" for k in sorted(values)]
    path.write_text("".join(lines), encoding="utf-8")
    return value


def reset_value(key: str | None = None) -> None:
    """Drop one key, or the whole file when *key* is None. Unknown keys ignored."""
    path = config_file_path()
    if key is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    if key not in ALLOWED:
        raise ConfigError(f"unknown config key '{key}' (known: merge.strategy, merge.push)")
    values = read_config()
    values.pop(key, None)
    if not values:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={values[k]}\n" for k in sorted(values)]
    path.write_text("".join(lines), encoding="utf-8")
