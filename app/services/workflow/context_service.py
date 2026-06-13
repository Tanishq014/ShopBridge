from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.barcode_service import normalize_barcode
from app.services.settings_service import (
    get_barcode_settings,
    get_price_code_settings,
    get_pricing_settings,
    get_template_field_settings,
)
from app.services.template_folder_service import scan_bartender_template_folder, template_path_exists
from app.services.workflow.form_state_service import family_payload, size_values, variant_payload
from app.services.workflow.query_service import (
    active_families,
    active_templates,
    recent_print_jobs,
    recent_templates,
    recent_variants,
    search_variants,
)
from app.services.workflow.template_field_service import template_payload


def workflow_context(
    request: Any,
    db: Session,
    *,
    category_choices: list[dict[str, str]],
    message: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    pricing_fields_visible: bool = True,
    selected_template_id: int | None = None,
    selected_category: str = "clothes",
    initial_variant_id: int | None = None,
    initial_duplicate: bool = False,
    initial_barcode: str = "",
) -> dict[str, object]:
    scan_bartender_template_folder(db)
    families = active_families(db)
    template_rows = active_templates(db)
    variants = search_variants(db)
    recent_variant_rows = recent_variants(db)
    recent_jobs = recent_print_jobs(db, 10)
    recent_template_rows = recent_templates(db, template_rows)

    template_payloads = [template_payload(template) for template in template_rows]
    recent_template_ids = {template.id for template in recent_template_rows}
    for payload in template_payloads:
        payload["recent"] = payload["id"] in recent_template_ids

    price_code_settings = get_price_code_settings()
    barcode_settings = get_barcode_settings()
    return {
        "request": request,
        "message": None,
        "warning": warning,
        "error": None,
        "workflow_message": message,
        "workflow_error": error,
        "categories": category_choices,
        "families": families,
        "families_json": [family_payload(family) for family in families],
        "template_rows": template_rows,
        "templates_json": template_payloads,
        "variants_json": [variant_payload(variant) for variant in variants],
        "recent_items": recent_variant_rows[:12],
        "recent_templates": recent_template_rows,
        "recent_jobs": recent_jobs,
        "size_values_json": size_values(variants, category_choices),
        "selected_template_id": selected_template_id,
        "selected_category": selected_category,
        "initial_variant_id": initial_variant_id,
        "initial_duplicate": initial_duplicate,
        "initial_barcode": normalize_barcode(initial_barcode),
        "pricing_settings": get_pricing_settings(),
        "price_code_settings": price_code_settings,
        "price_code_settings_json": {
            "digit_to_code": price_code_settings.digit_to_code,
            "code_to_digit": price_code_settings.code_to_digit,
            "price_code_letters": price_code_settings.price_code_letters,
            "allow_extraction": price_code_settings.allow_extraction,
        },
        "barcode_settings": barcode_settings,
        "barcode_settings_json": {
            "default_length": barcode_settings.default_length,
            "allowed_chars": barcode_settings.allowed_chars,
        },
        "pricing_fields_visible": pricing_fields_visible,
        "optional_template_fields": list(get_template_field_settings().resolved_optional_fields),
        "template_path_exists": template_path_exists,
        "template_warning": (
            "No active template was found. Add one in Settings -> Templates."
            if not template_rows
            else (
                None
                if any(template_path_exists(template) for template in template_rows)
                else "Templates exist, but their .btw file paths are missing on this PC. Fix the path in Settings before extracting fields or printing."
            )
        ),
    }
