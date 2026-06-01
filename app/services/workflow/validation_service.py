from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.models import LabelVariant, TemplateMaster
from app.services.workflow.form_state_service import parse_extra_field_values, variant_template_id


def decimal_or_none(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def int_or_none(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def same_text(left: str | None, right: str | None) -> bool:
    return (left or "").strip().lower() == (right or "").strip().lower()


def same_money(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return left.quantize(Decimal("0.01")) == right.quantize(Decimal("0.01"))


def price_changed(
    variant: LabelVariant | None,
    *,
    mrp: Decimal | None,
    selling_price: Decimal | None,
    coded_price: str,
) -> bool:
    if not variant:
        return False
    return (
        not same_money(variant.mrp, mrp)
        or not same_money(variant.selling_price, selling_price)
        or not same_text(variant.coded_price, coded_price)
    )


def label_details_changed(
    variant: LabelVariant | None,
    *,
    category: str,
    family_name: str,
    template: TemplateMaster,
    brand: str,
    item_display_name: str,
    article_no: str,
    size: str,
    batch_no: str,
    expiry: str,
    extra_field_values: dict[str, str],
    mrp: Decimal | None,
    selling_price: Decimal | None,
    coded_price: str,
) -> bool:
    if not variant:
        return False
    family = variant.family
    return (
        not same_text(family.category if family else "", category)
        or not same_text(family.family_name if family else "", family_name)
        or variant_template_id(variant) != template.id
        or not same_text(variant.brand, brand)
        or not same_text(variant.item_display_name, item_display_name)
        or not same_text(variant.article_no, article_no)
        or not same_text(variant.size, size)
        or not same_text(variant.batch_no, batch_no)
        or not same_text(variant.expiry, expiry)
        or parse_extra_field_values(variant.extra_field_values) != {
            field_name: field_value
            for field_name, field_value in extra_field_values.items()
            if str(field_value).strip()
        }
        or price_changed(
            variant,
            mrp=mrp,
            selling_price=selling_price,
            coded_price=coded_price,
        )
    )
