from __future__ import annotations

import json
from dataclasses import dataclass

from app.config import BARTENDER_MODE, DATA_DIR, SHOW_BARTENDER_WINDOW


BARTENDER_MODE_KEY = "bartender_mode"
SHOW_BARTENDER_WINDOW_KEY = "show_bartender_window"
VALID_BARTENDER_MODES = {"activex", "csv"}
BARCODE_MODE_KEY = "barcode_mode"
BARCODE_LENGTH_KEY = "barcode_length"
BARCODE_DEFAULTS_VERSION_KEY = "barcode_defaults_version"
BARCODE_GENERATION_MODE_KEY = "barcode_generation_mode"
DEFAULT_BARCODE_LENGTH_KEY = "default_barcode_length"
BARCODE_ALLOWED_CHARS_KEY = "barcode_allowed_chars"
BARCODE_GENERATION_MODE = "template_length_safe_alphanumeric"
DEFAULT_BARCODE_LENGTH = 7
DEFAULT_BARCODE_ALLOWED_CHARS = "23456789BFGJKLMQRUVWXY"
LEGACY_BARCODE_ALLOWED_CHARS = "23456789BFGJKLMNQRUVWXY"
BARCODE_DEFAULTS_VERSION = "2"
VALID_BARCODE_MODES = {BARCODE_GENERATION_MODE}
MRP_ROUNDING_KEY = "mrp_rounding"
MRP_TRUNCATE_DECIMAL_KEY = "mrp_truncate_decimal"
DEFAULT_MRP_ROUNDING = 9
VALID_MRP_ROUNDING = {1, 5, 10, 9}
PRICE_CODE_DIGIT_MAP_KEY = "price_code_digit_map"
ALLOW_PRICE_CODE_EXTRACTION_KEY = "allow_price_code_extraction"
EMPTY_PRICE_CODE_DIGIT_MAP = {str(digit): "" for digit in range(10)}

UPI_VPA_1_KEY = "upi_vpa_1"
UPI_KEY_1_KEY = "upi_key_1"
UPI_VPA_2_KEY = "upi_vpa_2"
UPI_KEY_2_KEY = "upi_key_2"
UPI_DEFAULT_VPA_KEY = "upi_default_vpa"
RECEIPT_PRINTER_NAME_KEY = "receipt_printer_name"


@dataclass(frozen=True)
class UpiSettings:
    vpa_1: str
    key_1: str
    vpa_2: str
    key_2: str
    default_vpa: str


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
    mrp_truncate_decimal: bool


OPTIONAL_TEMPLATE_FIELDS_KEY = "optional_template_fields"

# The user requested fields other than billing item, selling/code, mrp to be optional by default.
DEFAULT_OPTIONAL_TEMPLATE_FIELDS = {
    "article",
    "article_no",
    "brand",
    "item_display_name",
    "design",
    "size",
    "batch_no",
    "expiry",
    "margin_percent",
    "barcode",
    "tally_item_name"
}


OPTIONAL_FIELD_ALIASES = {
    "article": {"article", "article_no"},
    "article_no": {"article", "article_no"},
    "item_display_name": {"item_display_name", "design"},
    "design": {"item_display_name", "design"},
    "selling_price": {"selling_price", "rate"},
    "rate": {"selling_price", "rate"},
    "batch_no": {"batch_no", "shade", "shade_color"},
    "shade": {"batch_no", "shade", "shade_color"},
    "shade_color": {"batch_no", "shade", "shade_color"},
}

@dataclass(frozen=True)
class TemplateFieldSettings:
    optional_fields: set[str]

    def is_optional(self, field_name: str) -> bool:
        clean_name = field_name.strip().lower()
        if clean_name in self.optional_fields:
            return True
        aliases = OPTIONAL_FIELD_ALIASES.get(clean_name, set())
        return bool(aliases & self.optional_fields)

    @property
    def resolved_optional_fields(self) -> set[str]:
        resolved = set(self.optional_fields)
        for field in self.optional_fields:
            resolved.update(OPTIONAL_FIELD_ALIASES.get(field, set()))
        return resolved


@dataclass(frozen=True)
class PriceCodeSettings:
    digit_to_code: dict[str, str]
    allow_extraction: bool

    @property
    def code_to_digit(self) -> dict[str, str]:
        reverse: dict[str, str] = {}
        for digit, code in self.digit_to_code.items():
            for clean_code in _price_code_aliases(code):
                reverse[clean_code] = digit
        return reverse

    @property
    def price_code_letters(self) -> str:
        letters: list[str] = []
        seen: set[str] = set()
        for code in self.digit_to_code.values():
            for alias in _price_code_aliases(code):
                for char in alias:
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
    if settings.get(BARCODE_DEFAULTS_VERSION_KEY) != BARCODE_DEFAULTS_VERSION:
        if settings.get(DEFAULT_BARCODE_LENGTH_KEY, settings.get(BARCODE_LENGTH_KEY, "")) == "6":
            settings[DEFAULT_BARCODE_LENGTH_KEY] = str(DEFAULT_BARCODE_LENGTH)
            changed = True
        if settings.get(BARCODE_ALLOWED_CHARS_KEY, "") == LEGACY_BARCODE_ALLOWED_CHARS:
            settings[BARCODE_ALLOWED_CHARS_KEY] = DEFAULT_BARCODE_ALLOWED_CHARS
            changed = True
        settings[BARCODE_DEFAULTS_VERSION_KEY] = BARCODE_DEFAULTS_VERSION
        changed = True
    if BARCODE_GENERATION_MODE_KEY not in settings:
        settings[BARCODE_GENERATION_MODE_KEY] = settings.get(BARCODE_MODE_KEY, BARCODE_GENERATION_MODE)
        changed = True
    if DEFAULT_BARCODE_LENGTH_KEY not in settings:
        settings[DEFAULT_BARCODE_LENGTH_KEY] = settings.get(BARCODE_LENGTH_KEY, str(DEFAULT_BARCODE_LENGTH))
        changed = True
    if BARCODE_ALLOWED_CHARS_KEY not in settings:
        settings[BARCODE_ALLOWED_CHARS_KEY] = DEFAULT_BARCODE_ALLOWED_CHARS
        changed = True
    if MRP_ROUNDING_KEY not in settings:
        settings[MRP_ROUNDING_KEY] = str(DEFAULT_MRP_ROUNDING)
        changed = True
    if MRP_TRUNCATE_DECIMAL_KEY not in settings:
        settings[MRP_TRUNCATE_DECIMAL_KEY] = "false"
        changed = True
    if PRICE_CODE_DIGIT_MAP_KEY not in settings:
        settings[PRICE_CODE_DIGIT_MAP_KEY] = json.dumps(EMPTY_PRICE_CODE_DIGIT_MAP, ensure_ascii=True, sort_keys=True)
        changed = True
    if ALLOW_PRICE_CODE_EXTRACTION_KEY not in settings:
        settings[ALLOW_PRICE_CODE_EXTRACTION_KEY] = "true"
        changed = True
    if UPI_VPA_1_KEY not in settings:
        settings[UPI_VPA_1_KEY] = ""
        changed = True
    if UPI_KEY_1_KEY not in settings:
        settings[UPI_KEY_1_KEY] = "1"
        changed = True
    if UPI_VPA_2_KEY not in settings:
        settings[UPI_VPA_2_KEY] = ""
        changed = True
    if UPI_KEY_2_KEY not in settings:
        settings[UPI_KEY_2_KEY] = "2"
        changed = True
    if UPI_DEFAULT_VPA_KEY not in settings:
        settings[UPI_DEFAULT_VPA_KEY] = ""
        changed = True
    if OPTIONAL_TEMPLATE_FIELDS_KEY not in settings:
        settings[OPTIONAL_TEMPLATE_FIELDS_KEY] = json.dumps(list(DEFAULT_OPTIONAL_TEMPLATE_FIELDS))
        changed = True
    if changed:
        _write_settings(settings)


def get_template_field_settings() -> TemplateFieldSettings:
    ensure_default_settings()
    settings = _read_settings()
    raw = settings.get(OPTIONAL_TEMPLATE_FIELDS_KEY, "[]")
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            parsed = []
    except (TypeError, json.JSONDecodeError):
        parsed = []
    return TemplateFieldSettings(optional_fields={str(item).strip().lower() for item in parsed if item})


def save_template_field_settings(*, optional_fields: list[str]) -> TemplateFieldSettings:
    settings = _read_settings()
    clean_fields = list({str(f).strip().lower() for f in optional_fields if f})
    settings[OPTIONAL_TEMPLATE_FIELDS_KEY] = json.dumps(clean_fields)
    _write_settings(settings)
    return get_template_field_settings()


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
        length = int(value or DEFAULT_BARCODE_LENGTH)
    except (TypeError, ValueError):
        length = DEFAULT_BARCODE_LENGTH
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


def _price_code_aliases(value: str | None) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for part in str(value or "").split(","):
        clean = part.strip().upper()
        if clean and clean not in seen:
            aliases.append(clean)
            seen.add(clean)
    return aliases


def _price_code_digit_map(value: str | dict[str, str] | None, *, reject_duplicates: bool = False) -> dict[str, str]:
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
    used_codes: dict[str, str] = {}
    for digit in range(10):
        key = str(digit)
        aliases = _price_code_aliases(str(raw_map.get(key, "") or ""))
        clean_aliases: list[str] = []
        for alias in aliases:
            previous_digit = used_codes.get(alias)
            if previous_digit is not None and previous_digit != key:
                if reject_duplicates:
                    raise ValueError(f"Price code alias '{alias}' is assigned to both digit {previous_digit} and digit {key}.")
                continue
            used_codes[alias] = key
            clean_aliases.append(alias)
        digit_map[key] = ",".join(clean_aliases)
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
    return PricingSettings(
        mrp_rounding=_mrp_rounding(settings.get(MRP_ROUNDING_KEY)),
        mrp_truncate_decimal=_parse_bool(settings.get(MRP_TRUNCATE_DECIMAL_KEY), default=False),
    )


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


def save_pricing_settings(*, mrp_rounding: int, mrp_truncate_decimal: bool) -> PricingSettings:
    settings = _read_settings()
    settings[MRP_ROUNDING_KEY] = str(_mrp_rounding(mrp_rounding))
    settings[MRP_TRUNCATE_DECIMAL_KEY] = _bool_text(mrp_truncate_decimal)
    _write_settings(settings)
    return get_pricing_settings()


def save_price_code_settings(
    *,
    digit_to_code: dict[str, str],
    allow_extraction: bool,
) -> PriceCodeSettings:
    settings = _read_settings()
    clean_map = _price_code_digit_map(digit_to_code, reject_duplicates=True)
    settings[PRICE_CODE_DIGIT_MAP_KEY] = json.dumps(clean_map, ensure_ascii=True, sort_keys=True)
    settings[ALLOW_PRICE_CODE_EXTRACTION_KEY] = _bool_text(allow_extraction)
    _write_settings(settings)
    return get_price_code_settings()


def get_upi_settings() -> UpiSettings:
    ensure_default_settings()
    settings = _read_settings()
    return UpiSettings(
        vpa_1=settings.get(UPI_VPA_1_KEY, ""),
        key_1=settings.get(UPI_KEY_1_KEY, "1"),
        vpa_2=settings.get(UPI_VPA_2_KEY, ""),
        key_2=settings.get(UPI_KEY_2_KEY, "2"),
        default_vpa=settings.get(UPI_DEFAULT_VPA_KEY, ""),
    )


def save_upi_settings(
    *,
    vpa_1: str,
    key_1: str,
    vpa_2: str,
    key_2: str,
    default_vpa: str,
) -> UpiSettings:
    clean_vpa_1 = vpa_1.strip()
    clean_key_1 = key_1.strip().lower()
    clean_vpa_2 = vpa_2.strip()
    clean_key_2 = key_2.strip().lower()

    reserved_keys = {"enter", "escape", "esc", "ctrl", "alt", "shift", "n", "h", "x", "y"}

    if clean_vpa_1:
        if not clean_key_1 or len(clean_key_1) != 1:
            raise ValueError("Hotkey 1 must be exactly one visible character.")
        if clean_key_1 in reserved_keys:
            raise ValueError(f"Hotkey 1 cannot be a reserved key: '{clean_key_1}'")
            
    if clean_vpa_2:
        if not clean_key_2 or len(clean_key_2) != 1:
            raise ValueError("Hotkey 2 must be exactly one visible character.")
        if clean_key_2 in reserved_keys:
            raise ValueError(f"Hotkey 2 cannot be a reserved key: '{clean_key_2}'")

    if clean_vpa_1 and clean_vpa_2 and clean_key_1 == clean_key_2:
        raise ValueError("Hotkeys cannot be the same if both VPAs are filled.")

    settings = _read_settings()
    settings[UPI_VPA_1_KEY] = clean_vpa_1
    settings[UPI_KEY_1_KEY] = clean_key_1 if clean_vpa_1 else (clean_key_1 or "1")
    settings[UPI_VPA_2_KEY] = clean_vpa_2
    settings[UPI_KEY_2_KEY] = clean_key_2 if clean_vpa_2 else (clean_key_2 or "2")
    settings[UPI_DEFAULT_VPA_KEY] = default_vpa.strip()
    _write_settings(settings)
    return get_upi_settings()

def get_receipt_printer_name() -> str:
    return _read_settings().get(RECEIPT_PRINTER_NAME_KEY, "")

def set_receipt_printer_name(name: str) -> None:
    settings = _read_settings()
    settings[RECEIPT_PRINTER_NAME_KEY] = (name or "").strip()
    _write_settings(settings)
