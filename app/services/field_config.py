from __future__ import annotations

import json
from collections.abc import Mapping
import re


SUPPORTED_FIELDS = [
    {"name": "brand", "label": "Brand"},
    {"name": "item_display_name", "label": "Sticker Name"},
    {"name": "design", "label": "Design"},
    {"name": "family_name", "label": "Billing Item"},
    {"name": "barcode", "label": "Barcode"},
    {"name": "article", "label": "Article No"},
    {"name": "size", "label": "Size"},
    {"name": "batch_no", "label": "Batch No"},
    {"name": "expiry", "label": "Expiry"},
    {"name": "mrp", "label": "MRP"},
    {"name": "selling_price", "label": "Selling Price"},
    {"name": "coded_price", "label": "Code"},
]

SUPPORTED_FIELD_NAMES = [field["name"] for field in SUPPORTED_FIELDS]
FIELD_LABELS = {field["name"]: field["label"] for field in SUPPORTED_FIELDS}
FIELD_LABELS["article_no"] = "Article No"

FIELD_ALIASES = {
    "articlenumber": "article",
    "articleno": "article",
    "batch": "batch_no",
    "batchno": "batch_no",
    "batchnumber": "batch_no",
    "bath": "batch_no",
    "code": "coded_price",
    "codedprice": "coded_price",
    "design": "design",
    "itemname": "item_display_name",
    "itemdisplayname": "item_display_name",
    "name": "item_display_name",
    "productname": "item_display_name",
    "stickername": "item_display_name",
    "sellingprice": "selling_price",
}


def normalize_field_name(field_name: str) -> str:
    clean_name = str(field_name or "").strip()
    if not clean_name:
        return ""
    normalized_key = re.sub(r"[^a-z0-9]+", "", clean_name.lower())
    return FIELD_ALIASES.get(normalized_key, clean_name.lower())
DEFAULT_REQUIRED_FIELDS = [
    "brand",
    "item_display_name",
    "article",
    "size",
    "mrp",
    "coded_price",
    "barcode",
]


def parse_required_fields(value: str | None) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    for raw_field in (value or "").split(","):
        field = normalize_field_name(raw_field)
        if not field or field in seen:
            continue
        fields.append(field)
        seen.add(field)
    return fields


def format_required_fields(fields: list[str] | tuple[str, ...] | None) -> str:
    return ",".join(parse_required_fields(",".join(fields or [])))


def merge_required_fields(selected_fields: list[str] | None, raw_fields: str | None) -> str:
    merged = list(selected_fields or [])
    merged.extend(parse_required_fields(raw_fields))
    return format_required_fields(merged)


def default_required_fields_csv() -> str:
    return format_required_fields(DEFAULT_REQUIRED_FIELDS)


def field_label(field_name: str) -> str:
    return FIELD_LABELS.get(field_name, field_name)


def parse_field_defaults(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        raw_defaults = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw_defaults, dict):
        return {}

    defaults: dict[str, str] = {}
    for field_name, field_value in raw_defaults.items():
        clean_name = normalize_field_name(str(field_name))
        if not clean_name or field_value is None:
            continue
        defaults[clean_name] = str(field_value).strip()
    return defaults


def format_field_defaults(values: Mapping[str, object] | None) -> str:
    clean_values: dict[str, str] = {}
    for field_name, field_value in (values or {}).items():
        clean_name = normalize_field_name(str(field_name))
        if not clean_name or field_value is None:
            continue
        clean_value = str(field_value).strip()
        if clean_value:
            clean_values[clean_name] = clean_value
    if not clean_values:
        return ""
    return json.dumps(clean_values, ensure_ascii=True, sort_keys=True)
