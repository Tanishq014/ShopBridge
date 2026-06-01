from __future__ import annotations

from decimal import Decimal

from app.services.field_config import field_label
from app.services.price_code_service import PriceCodeCandidate


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def candidate_payload(candidate: PriceCodeCandidate) -> dict[str, str]:
    return {
        "key": candidate.key,
        "source_field": candidate.source_field,
        "raw_value": candidate.raw_value,
        "code": candidate.code,
        "selling_price": candidate.selling_price_text,
        "label": (
            f"{field_label(candidate.source_field)}: {candidate.raw_value} "
            f"-> {candidate.code} -> {candidate.selling_price_text}"
        ),
    }


def find_candidate_by_key(candidates: list[PriceCodeCandidate], key: str) -> PriceCodeCandidate | None:
    for candidate in candidates:
        if candidate.key == key:
            return candidate
    return None
