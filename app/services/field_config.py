from __future__ import annotations


SUPPORTED_FIELDS = [
    {"name": "brand", "label": "Brand"},
    {"name": "item_display_name", "label": "Sticker Name"},
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
        field = raw_field.strip()
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
