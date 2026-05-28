from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import BARTENDER_MODE, DATA_DIR, SHOW_BARTENDER_WINDOW


BARTENDER_MODE_KEY = "bartender_mode"
SHOW_BARTENDER_WINDOW_KEY = "show_bartender_window"
VALID_BARTENDER_MODES = {"activex", "csv"}
BARCODE_MODE_KEY = "barcode_mode"
BARCODE_LENGTH_KEY = "barcode_length"
BARCODE_GENERATION_MODE_KEY = "barcode_generation_mode"
DEFAULT_BARCODE_LENGTH_KEY = "default_barcode_length"
BARCODE_ALLOWED_CHARS_KEY = "barcode_allowed_chars"
BARCODE_GENERATION_MODE = "template_length_safe_alphanumeric"
DEFAULT_BARCODE_ALLOWED_CHARS = "23456789BFGJKLMNQRUVWXY"
VALID_BARCODE_MODES = {BARCODE_GENERATION_MODE}


@dataclass(frozen=True)
class BarTenderSettings:
    mode: str
    show_bartender_window: bool


@dataclass(frozen=True)
class BarcodeSettings:
    generation_mode: str
    default_length: int
    allowed_chars: str

    @property
    def mode(self) -> str:
        return self.generation_mode

    @property
    def length(self) -> int:
        return self.default_length


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
    if BARCODE_GENERATION_MODE_KEY not in settings:
        settings[BARCODE_GENERATION_MODE_KEY] = settings.get(BARCODE_MODE_KEY, BARCODE_GENERATION_MODE)
        changed = True
    if DEFAULT_BARCODE_LENGTH_KEY not in settings:
        settings[DEFAULT_BARCODE_LENGTH_KEY] = settings.get(BARCODE_LENGTH_KEY, "6")
        changed = True
    if BARCODE_ALLOWED_CHARS_KEY not in settings:
        settings[BARCODE_ALLOWED_CHARS_KEY] = DEFAULT_BARCODE_ALLOWED_CHARS
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


def _barcode_length(value: str | None) -> int:
    try:
        length = int(value or 6)
    except (TypeError, ValueError):
        length = 6
    return min(8, max(5, length))


def _barcode_allowed_chars(value: str | None) -> str:
    allowed = []
    seen: set[str] = set()
    for char in (value or DEFAULT_BARCODE_ALLOWED_CHARS).upper():
        if char in DEFAULT_BARCODE_ALLOWED_CHARS and char not in seen:
            allowed.append(char)
            seen.add(char)
    return "".join(allowed) or DEFAULT_BARCODE_ALLOWED_CHARS


def get_barcode_settings() -> BarcodeSettings:
    ensure_default_settings()
    settings = _read_settings()
    mode = settings.get(BARCODE_GENERATION_MODE_KEY, BARCODE_GENERATION_MODE).strip().lower()
    if mode not in VALID_BARCODE_MODES:
        mode = BARCODE_GENERATION_MODE
    return BarcodeSettings(
        generation_mode=mode,
        default_length=_barcode_length(settings.get(DEFAULT_BARCODE_LENGTH_KEY)),
        allowed_chars=_barcode_allowed_chars(settings.get(BARCODE_ALLOWED_CHARS_KEY)),
    )


def save_barcode_settings(
    *,
    generation_mode: str,
    default_length: int,
    allowed_chars: str,
) -> BarcodeSettings:
    clean_mode = generation_mode.strip().lower()
    if clean_mode not in VALID_BARCODE_MODES:
        clean_mode = BARCODE_GENERATION_MODE

    settings = _read_settings()
    settings[BARCODE_GENERATION_MODE_KEY] = clean_mode
    settings[DEFAULT_BARCODE_LENGTH_KEY] = str(_barcode_length(str(default_length)))
    settings[BARCODE_ALLOWED_CHARS_KEY] = _barcode_allowed_chars(allowed_chars)
    _write_settings(settings)
    return get_barcode_settings()
