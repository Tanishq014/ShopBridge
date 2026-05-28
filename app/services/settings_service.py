from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import BARTENDER_MODE, DATA_DIR, SHOW_BARTENDER_WINDOW


BARTENDER_MODE_KEY = "bartender_mode"
SHOW_BARTENDER_WINDOW_KEY = "show_bartender_window"
VALID_BARTENDER_MODES = {"activex", "csv"}


@dataclass(frozen=True)
class BarTenderSettings:
    mode: str
    show_bartender_window: bool


def _default_mode() -> str:
    return BARTENDER_MODE if BARTENDER_MODE in VALID_BARTENDER_MODES else "activex"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _settings_path():
    return DATA_DIR / "settings.json"


def _read_settings() -> dict[str, str]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def _write_settings(settings: dict[str, str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(
        json.dumps(settings, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def ensure_default_settings() -> None:
    settings = _read_settings()
    changed = False
    if BARTENDER_MODE_KEY not in settings:
        settings[BARTENDER_MODE_KEY] = _default_mode()
        changed = True
    if SHOW_BARTENDER_WINDOW_KEY not in settings:
        settings[SHOW_BARTENDER_WINDOW_KEY] = _bool_text(SHOW_BARTENDER_WINDOW)
        changed = True
    if changed:
        _write_settings(settings)


def get_bartender_settings() -> BarTenderSettings:
    ensure_default_settings()
    settings = _read_settings()

    mode = settings.get(BARTENDER_MODE_KEY, _default_mode()) or _default_mode()
    mode = mode.strip().lower()
    if mode not in VALID_BARTENDER_MODES:
        mode = "activex"

    return BarTenderSettings(
        mode=mode,
        show_bartender_window=_parse_bool(
            settings.get(SHOW_BARTENDER_WINDOW_KEY),
            default=SHOW_BARTENDER_WINDOW,
        ),
    )


def save_bartender_settings(
    *,
    mode: str,
    show_bartender_window: bool,
) -> BarTenderSettings:
    clean_mode = mode.strip().lower()
    if clean_mode not in VALID_BARTENDER_MODES:
        clean_mode = "activex"

    settings = _read_settings()
    settings[BARTENDER_MODE_KEY] = clean_mode
    settings[SHOW_BARTENDER_WINDOW_KEY] = _bool_text(show_bartender_window)
    _write_settings(settings)
    return get_bartender_settings()
