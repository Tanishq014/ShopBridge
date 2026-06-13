from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from app.services.field_config import normalize_field_name
from app.services.settings_service import PriceCodeSettings, get_price_code_settings


PRIORITY_PRICE_CODE_FIELDS = {"coded_price"}


@dataclass(frozen=True)
class PriceCodeCandidate:
    source_field: str
    raw_value: str
    code: str
    selling_price: Decimal
    priority: bool = False

    @property
    def selling_price_text(self) -> str:
        if self.selling_price == self.selling_price.to_integral_value():
            return str(int(self.selling_price))
        return f"{self.selling_price:.2f}"

    @property
    def key(self) -> str:
        return f"{self.source_field}|{self.code}|{self.selling_price_text}"


def _settings_or_default(settings: PriceCodeSettings | None) -> PriceCodeSettings:
    return settings if settings is not None else get_price_code_settings()


def generate_coded_price(
    price: Decimal | float | int | str | None,
    settings: PriceCodeSettings | None = None,
) -> str:
    if price in (None, ""):
        return ""

    try:
        amount = Decimal(str(price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return ""

    if amount < 0:
        return ""

    digit_to_code = _settings_or_default(settings).digit_to_code
    digits = str(int(amount))
    first_alias_by_digit = {
        digit: str(code or "").split(",", 1)[0].strip().upper()
        for digit, code in digit_to_code.items()
    }
    if any(not first_alias_by_digit.get(digit) for digit in digits):
        return ""
    try:
        return "".join(first_alias_by_digit.get(digit, "") for digit in digits)
    except KeyError:
        return ""
    except TypeError:
        return ""
    except ValueError:
        return ""


def _decode_group(group: str, settings: PriceCodeSettings) -> Decimal | None:
    code_to_digit = settings.code_to_digit
    if not group or not code_to_digit:
        return None

    mapped_letters = set(settings.price_code_letters.upper())
    group = "".join(c for c in group.upper() if c in mapped_letters)

    if not group:
        return None

    tokens = sorted(code_to_digit, key=len, reverse=True)
    matches: list[str] = []

    def walk(index: int, digits: list[str]) -> None:
        if len(matches) > 1:
            return
        if index == len(group):
            matches.append("".join(digits))
            return
        for token in tokens:
            if group.startswith(token, index):
                walk(index + len(token), [*digits, code_to_digit[token]])

    walk(0, [])
    if len(matches) != 1 or not matches[0]:
        return None
    try:
        return Decimal(matches[0])
    except InvalidOperation:
        return None


def _candidate_groups(raw_value: str, settings: PriceCodeSettings) -> list[str]:
    letters = settings.price_code_letters
    if not raw_value or not letters:
        return []
    pattern = f"[{re.escape(letters)}]+"
    return [match.group(0).upper() for match in re.finditer(pattern, raw_value.upper())]


def extract_candidates_from_field(
    source_field: str,
    raw_value: str,
    settings: PriceCodeSettings | None = None,
    *,
    priority: bool = False,
) -> list[PriceCodeCandidate]:
    clean_settings = _settings_or_default(settings)
    candidates: list[PriceCodeCandidate] = []
    seen: set[tuple[str, str]] = set()
    for group in _candidate_groups(str(raw_value or ""), clean_settings):
        selling_price = _decode_group(group, clean_settings)
        if selling_price is None:
            continue
        key = (source_field, group)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            PriceCodeCandidate(
                source_field=source_field,
                raw_value=str(raw_value or ""),
                code=group,
                selling_price=selling_price,
                priority=priority,
            )
        )
    return candidates


def extract_price_code_candidates(
    field_values: dict[str, str],
    template_fields: list[str],
    settings: PriceCodeSettings | None = None,
) -> tuple[list[PriceCodeCandidate], bool]:
    clean_settings = _settings_or_default(settings)
    if not clean_settings.allow_extraction:
        return [], False

    normalized_values = {
        normalize_field_name(field_name): "" if value is None else str(value)
        for field_name, value in field_values.items()
        if normalize_field_name(field_name)
    }
    normalized_template_fields = [normalize_field_name(field_name) for field_name in template_fields]
    priority_fields = [
        field_name
        for field_name in normalized_template_fields
        if field_name in PRIORITY_PRICE_CODE_FIELDS
    ]
    priority_candidates: list[PriceCodeCandidate] = []
    for field_name in priority_fields:
        priority_candidates.extend(
            extract_candidates_from_field(
                field_name,
                normalized_values.get(field_name, ""),
                clean_settings,
                priority=True,
            )
        )
    if priority_fields and priority_candidates:
        return _dedupe_candidates(priority_candidates), True
    return [], False


def _dedupe_candidates(candidates: list[PriceCodeCandidate]) -> list[PriceCodeCandidate]:
    deduped: list[PriceCodeCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.key in seen:
            continue
        deduped.append(candidate)
        seen.add(candidate.key)
    return deduped
