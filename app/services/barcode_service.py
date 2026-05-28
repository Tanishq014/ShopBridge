from __future__ import annotations

import secrets
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LabelVariant
from app.services.settings_service import get_barcode_settings


MAX_RANDOM_BARCODE_ATTEMPTS = 50


def normalize_barcode(value: str | None) -> str:
    return (value or "").strip().upper()


def barcode_exists(db: Session, barcode: str, exclude_variant_id: int | None = None) -> bool:
    query = select(LabelVariant).where(LabelVariant.barcode == barcode)
    if exclude_variant_id is not None:
        query = query.where(LabelVariant.id != exclude_variant_id)
    return db.scalar(query) is not None


def _barcode_length(template: Any | None = None) -> int:
    settings = get_barcode_settings()
    sample = normalize_barcode(getattr(template, "barcode_sample_value", "") if template else "")
    if not sample and template is not None:
        try:
            defaults = json.loads(getattr(template, "default_field_values", "") or "{}")
        except (TypeError, json.JSONDecodeError):
            defaults = {}
        if isinstance(defaults, dict):
            sample = normalize_barcode(defaults.get("barcode"))
    if sample:
        return min(8, max(5, len(sample)))
    return settings.default_length


def _has_consecutive_numbers(value: str) -> bool:
    previous_was_digit = False
    for char in value:
        current_is_digit = char.isdigit()
        if previous_was_digit and current_is_digit:
            return True
        previous_was_digit = current_is_digit
    return False


def _random_candidate(length: int, allowed_chars: str) -> str:
    return "".join(secrets.choice(allowed_chars) for _ in range(length))


def generate_configured_barcode(db: Session, template: Any | None = None) -> str:
    settings = get_barcode_settings()
    length = _barcode_length(template)
    allowed_chars = settings.allowed_chars

    for _ in range(MAX_RANDOM_BARCODE_ATTEMPTS):
        barcode = _random_candidate(length, allowed_chars)
        if _has_consecutive_numbers(barcode):
            continue
        if not barcode_exists(db, barcode):
            return barcode

    raise ValueError(
        f"Could not generate a unique barcode after {MAX_RANDOM_BARCODE_ATTEMPTS} attempts. "
        "Try increasing barcode length or check duplicate records."
    )


def assign_barcode(
    db: Session,
    requested_barcode: str | None = None,
    exclude_variant_id: int | None = None,
    template: Any | None = None,
) -> str:
    barcode = normalize_barcode(requested_barcode)
    if barcode:
        if barcode_exists(db, barcode, exclude_variant_id=exclude_variant_id):
            raise ValueError(f"Barcode already exists: {barcode}")
        return barcode

    return generate_configured_barcode(db, template=template)
