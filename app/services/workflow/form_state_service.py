from __future__ import annotations

import json

from app.models import LabelVariant, ProductFamily, TemplateMaster
from app.services.field_config import normalize_field_name
from app.services.time_service import format_local_datetime
from app.services.workflow.pricing_workflow_service import compact_money, money


def parse_extra_field_values(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        raw_values = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_values, dict):
        return {}

    values: dict[str, str] = {}
    for field_name, field_value in raw_values.items():
        clean_name = normalize_field_name(str(field_name))
        if not clean_name or field_value is None:
            continue
        values[clean_name] = str(field_value).strip()
    return values


def format_extra_field_values(values: dict[str, str]) -> str | None:
    clean_values = {
        normalize_field_name(field_name): str(field_value).strip()
        for field_name, field_value in values.items()
        if normalize_field_name(field_name) and str(field_value).strip()
    }
    if not clean_values:
        return None
    return json.dumps(clean_values, ensure_ascii=True, sort_keys=True)


def date_time(value) -> str:
    return format_local_datetime(value)


def family_payload(family: ProductFamily) -> dict[str, object]:
    return {
        "id": family.id,
        "family_name": family.family_name,
        "category": (family.category or "").strip().lower(),
        "default_template_id": family.default_template_id or "",
        "created_at": date_time(family.created_at),
        "updated_at": date_time(family.updated_at),
    }


def variant_template_id(variant: LabelVariant) -> int | None:
    return variant.template_id or variant.family.default_template_id


def variant_payload(variant: LabelVariant) -> dict[str, object]:
    template = variant.template or variant.family.default_template
    category = (variant.family.category or "").strip().lower()
    return {
        "id": variant.id,
        "search": " | ".join(
            part
            for part in [
                variant.barcode,
                variant.item_display_name,
                variant.brand,
                category,
                variant.article_no,
                variant.batch_no,
                variant.size,
                compact_money(variant.mrp),
                money(variant.selling_price),
                variant.coded_price,
                *[
                    value
                    for value in parse_extra_field_values(variant.extra_field_values).values()
                    if value
                ],
            ]
            if part
        ),
        "barcode": variant.barcode,
        "family_id": variant.family_id,
        "family_name": variant.family.family_name,
        "category": category,
        "brand": variant.brand or "",
        "item_display_name": variant.item_display_name,
        "article_no": variant.article_no or "",
        "size": variant.size or "",
        "batch_no": variant.batch_no or "",
        "expiry": variant.expiry or "",
        "mrp": compact_money(variant.mrp),
        "selling_price": money(variant.selling_price),
        "coded_price": variant.coded_price or "",
        "billing_price_missing": bool(variant.billing_price_missing),
        "extra_field_values": parse_extra_field_values(variant.extra_field_values),
        "template_id": variant_template_id(variant) or "",
        "template_name": template.template_name if template else "",
        "created_at": date_time(variant.created_at),
        "updated_at": date_time(variant.updated_at),
    }


def size_values(variants: list[LabelVariant], category_choices: list[dict[str, str]]) -> dict[str, list[str]]:
    values: dict[str, set[str]] = {choice["value"]: set() for choice in category_choices}
    for variant in variants:
        category = (variant.family.category or "").strip().lower()
        if category in values and variant.size:
            values[category].add(variant.size)
    return {category: sorted(sizes) for category, sizes in values.items()}
