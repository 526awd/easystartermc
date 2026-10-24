"""Key-based localization loaded from JSON language catalogs."""
import json
import locale
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_RESOURCE_DIR = Path(__file__).resolve().parent / "locales"
_SUPPORTED = {"zh_cn": "zh_CN", "zh": "zh_CN", "en_us": "en_US", "en": "en_US"}
_active_locale = "zh_CN"


def _system_locale() -> str:
    candidates = [os.environ.get(name, "") for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except (ValueError, TypeError):
        pass
    for candidate in candidates:
        language = candidate.lower().replace("-", "_")
        if language.startswith(("zh", "chinese")):
            return "zh_CN"
        if language.startswith("en"):
            return "en_US"
    return "en_US"


def set_locale(preference: str | None = "auto") -> str:
    """Set an explicit locale, or follow the host language when preference is auto."""
    global _active_locale
    value = str(preference or "auto").strip().lower().replace("-", "_")
    _active_locale = _SUPPORTED.get(value, _system_locale() if value in ("", "auto", "system") else "en_US")
    return _active_locale


def current_locale() -> str:
    return _active_locale


@lru_cache(maxsize=4)
def _messages(language: str) -> dict[str, str]:
    path = _RESOURCE_DIR / f"{language}.json"
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str) and not key.startswith("_")}


def language_name(preference: str | None = None) -> str:
    value = str(preference or _active_locale).strip().lower().replace("-", "_")
    selected = _SUPPORTED.get(value, _system_locale() if value in ("", "auto", "system") else "en_US")
    return _messages(selected).get("language.name", "English")


def tr(key: str, **values: object) -> str:
    """Return the message for a stable alphabetic key and format its values."""
    message = _messages(_active_locale).get(key)
    if message is None:
        message = _messages("zh_CN").get(key, key)
    try:
        return message.format(**values) if values else message
    except (KeyError, ValueError, IndexError):
        return message
