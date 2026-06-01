from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import TemplateMaster
from app.services.barcode_service import generate_configured_barcode
from app.services.bartender_activex_service import BarTenderActiveXError
from app.services.field_config import parse_required_fields
from app.services.price_code_service import generate_coded_price
from app.services.settings_service import get_bartender_settings, get_price_code_settings
from app.services.template_preview_service import refresh_cached_template_preview
from app.services.workflow.form_state_service import parse_extra_field_values
from app.services.workflow.pricing_workflow_service import money
from app.services.workflow.validation_service import decimal_or_none


def refresh_cached_preview_error(template: TemplateMaster) -> str | None:
    try:
        refresh_cached_template_preview(
            template,
            visible=get_bartender_settings().show_bartender_window,
        )
    except BarTenderActiveXError as exc:
        return f"Fields were extracted. Raw preview was not cached: {exc}"
    except Exception as exc:
        return f"Fields were extracted. Raw preview was not cached: {exc}"
    return None


def form_field_values(
    db: Session,
    template: TemplateMaster,
    *,
    barcode: str,
    brand: str,
    item_display_name: str,
    family_name: str,
    article_no: str,
    size: str,
    batch_no: str,
    expiry: str,
    mrp: str,
    selling_price: str,
    coded_price: str,
    extra_field_values: str = "",
) -> dict[str, str]:
    selling = decimal_or_none(selling_price)
    mrp_value = decimal_or_none(mrp)
    extras = parse_extra_field_values(extra_field_values)
    barcode_value = barcode.strip()
    required_fields = parse_required_fields(template.required_fields)
    if not barcode_value and "barcode" in required_fields:
        try:
            barcode_value = generate_configured_barcode(db, template=template)
        except ValueError:
            barcode_value = "manual"

    article_value = article_no.strip()
    item_name_value = item_display_name.strip() or family_name.strip()
    final_family_name = family_name.strip() or item_name_value
    price_code_settings = get_price_code_settings()
    coded = coded_price.strip() or generate_coded_price(selling, price_code_settings) or ""
    standard_values = {
        "barcode": barcode_value,
        "brand": brand.strip(),
        "item_display_name": item_name_value,
        "design": item_name_value,
        "family_name": final_family_name,
        "article": article_value,
        "article_no": article_value,
        "size": size.strip(),
        "batch_no": batch_no.strip(),
        "expiry": expiry.strip(),
        "mrp": money(mrp_value),
        "selling_price": money(selling),
        "coded_price": coded,
    }
    standard_values.update(extras)
    return {
        field_name: standard_values.get(field_name, "")
        for field_name in required_fields
    }
