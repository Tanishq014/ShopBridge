from __future__ import annotations

from app.models import TemplateMaster
from sqlalchemy.orm import Session

from app.services.bartender_activex_service import extract_named_substring_values
from app.services.field_config import (
    format_field_defaults,
    format_required_fields,
    parse_field_defaults,
    parse_required_fields,
)
from app.services.template_folder_service import template_file_changed_since_extract, template_file_mtime, template_path_exists
from app.services.template_preview_service import cached_template_preview_url


def template_payload(template: TemplateMaster) -> dict[str, object]:
    field_defaults = parse_field_defaults(template.default_field_values)
    field_defaults.pop("barcode", None)
    return {
        "id": template.id,
        "template_id": template.template_id,
        "template_name": template.template_name,
        "category": (template.category or "").strip().lower(),
        "label_size": template.label_size or "",
        "bartender_file_path": template.bartender_file_path or "",
        "required_fields": parse_required_fields(template.required_fields),
        "field_defaults": field_defaults,
        "path_exists": template_path_exists(template),
        "file_changed": template_file_changed_since_extract(template),
        "cached_preview_url": cached_template_preview_url(template),
        "recent": False,
    }


def extract_and_save_template_fields(db: Session, template: TemplateMaster) -> str:
    field_defaults = extract_named_substring_values(template.bartender_file_path)
    fields = list(field_defaults)
    barcode_sample = field_defaults.get("barcode", "").strip()
    default_values = {field: value for field, value in field_defaults.items() if field != "barcode"}
    template.required_fields = format_required_fields(fields)
    template.default_field_values = format_field_defaults(default_values)
    template.barcode_sample_value = barcode_sample or None
    template.fields_extracted_file_mtime = template_file_mtime(template)
    db.add(template)
    db.commit()
    db.refresh(template)
    return ", ".join(fields)
