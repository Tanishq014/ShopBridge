from __future__ import annotations

from app.models import TemplateMaster
from app.services.field_config import parse_field_defaults, parse_required_fields
from app.services.template_folder_service import template_file_changed_since_extract, template_path_exists
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
        "required_fields": parse_required_fields(template.required_fields),
        "field_defaults": field_defaults,
        "path_exists": template_path_exists(template),
        "file_changed": template_file_changed_since_extract(template),
        "cached_preview_url": cached_template_preview_url(template),
        "recent": False,
    }
