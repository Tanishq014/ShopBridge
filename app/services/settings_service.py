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
MRP_ROUNDING_KEY = "mrp_rounding"
DEFAULT_MRP_ROUNDING = 5
VALID_MRP_ROUNDING = {1, 5, 10, 9}
PRICE_CODE_DIGIT_MAP_KEY = "price_code_digit_map"
ALLOW_PRICE_CODE_EXTRACTION_KEY = "allow_price_code_extraction"
EMPTY_PRICE_CODE_DIGIT_MAP = {str(digit): "" for digit in range(10)}


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


@dataclass(frozen=True)
class PricingSettings:
    mrp_rounding: int


@dataclass(frozen=True)
class PriceCodeSettings:
    digit_to_code: dict[str, str]
    allow_extraction: bool

    @property
    def code_to_digit(self) -> dict[str, str]:
        reverse: dict[str, str] = {}
        for digit, code in self.digit_to_code.items():
            clean_code = str(code or "").strip().upper()
            if clean_code:
                reverse[clean_code] = digit
        return reverse

    @property
    def price_code_letters(self) -> str:
        letters: list[str] = []
        seen: set[str] = set()
        for code in self.digit_to_code.values():
            for char in str(code or "").strip().upper():
                if char and char not in seen:
                    letters.append(char)
                    seen.add(char)
        return "".join(letters)


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
    if MRP_ROUNDING_KEY not in settings:
        settings[MRP_ROUNDING_KEY] = str(DEFAULT_MRP_ROUNDING)
        changed = True
    if PRICE_CODE_DIGIT_MAP_KEY not in settings:
        settings[PRICE_CODE_DIGIT_MAP_KEY] = json.dumps(EMPTY_PRICE_CODE_DIGIT_MAP, ensure_ascii=True, sort_keys=True)
        changed = True
    if ALLOW_PRICE_CODE_EXTRACTION_KEY not in settings:
        settings[ALLOW_PRICE_CODE_EXTRACTION_KEY] = "true"
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


def _mrp_rounding(value: str | int | None) -> int:
    try:
        rounding = int(value or DEFAULT_MRP_ROUNDING)
    except (TypeError, ValueError):
        rounding = DEFAULT_MRP_ROUNDING
    return rounding if rounding in VALID_MRP_ROUNDING else DEFAULT_MRP_ROUNDING


def _price_code_digit_map(value: str | dict[str, str] | None) -> dict[str, str]:
    if isinstance(value, dict):
        raw_map = value
    else:
        try:
            raw_map = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            raw_map = {}
    if not isinstance(raw_map, dict):
        raw_map = {}

    digit_map: dict[str, str] = {}
    used_codes: set[str] = set()
    for digit in range(10):
        key = str(digit)
        clean_code = str(raw_map.get(key, "") or "").strip().upper()
        if clean_code and clean_code not in used_codes:
            digit_map[key] = clean_code
            used_codes.add(clean_code)
        else:
            digit_map[key] = ""
    return digit_map


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


def get_pricing_settings() -> PricingSettings:
    ensure_default_settings()
    settings = _read_settings()
    return PricingSettings(mrp_rounding=_mrp_rounding(settings.get(MRP_ROUNDING_KEY)))


def get_price_code_settings() -> PriceCodeSettings:
    ensure_default_settings()
    settings = _read_settings()
    return PriceCodeSettings(
        digit_to_code=_price_code_digit_map(settings.get(PRICE_CODE_DIGIT_MAP_KEY)),
        allow_extraction=_parse_bool(settings.get(ALLOW_PRICE_CODE_EXTRACTION_KEY), default=True),
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


def save_pricing_settings(*, mrp_rounding: int) -> PricingSettings:
    settings = _read_settings()
    settings[MRP_ROUNDING_KEY] = str(_mrp_rounding(mrp_rounding))
    _write_settings(settings)
    return get_pricing_settings()


def save_price_code_settings(
    *,
    digit_to_code: dict[str, str],
    allow_extraction: bool,
) -> PriceCodeSettings:
    settings = _read_settings()
    clean_map = _price_code_digit_map(digit_to_code)
    settings[PRICE_CODE_DIGIT_MAP_KEY] = json.dumps(clean_map, ensure_ascii=True, sort_keys=True)
    settings[ALLOW_PRICE_CODE_EXTRACTION_KEY] = _bool_text(allow_extraction)
    _write_settings(settings)
    return get_price_code_settings()
