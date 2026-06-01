from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LabelVariant, ProductFamily, TemplateMaster
from app.services.workflow.form_state_service import parse_extra_field_values
from app.services.workflow.validation_service import same_money, same_text


def find_or_create_family(
    db: Session,
    category: str,
    family_id: int | None,
    family_name: str,
    item_display_name: str,
) -> ProductFamily:
    final_name = (family_name or item_display_name).strip()
    if family_id:
        family = db.get(ProductFamily, family_id)
        if family:
            if final_name and family.family_name.strip().lower() != final_name.lower():
                family_id = None
            else:
                if category and family.category != category:
                    family.category = category
                    db.add(family)
                return family

    if not final_name:
        final_name = item_display_name.strip()

    family = db.scalar(
        select(ProductFamily).where(func.lower(ProductFamily.family_name) == final_name.lower())
    )
    if family:
        if category and family.category != category:
            family.category = category
            family.active_status = True
            db.add(family)
        return family

    family = ProductFamily(
        family_name=final_name,
        tally_stock_item_name=None,
        category=category,
        default_tax_rate=0,
        default_unit="PCS",
        active_status=True,
    )
    db.add(family)
    db.flush()
    return family


def find_exact_variant(
    db: Session,
    *,
    category: str,
    template: TemplateMaster,
    required_fields: list[str],
    family_name: str,
    item_display_name: str,
    brand: str,
    article_no: str,
    size: str,
    batch_no: str,
    expiry: str,
    extra_field_values: dict[str, str],
    mrp: Decimal | None,
    selling_price: Decimal | None,
    coded_price: str,
) -> LabelVariant | None:
    query = (
        select(LabelVariant)
        .join(ProductFamily)
        .where(LabelVariant.status == "active")
        .where(func.lower(LabelVariant.item_display_name) == item_display_name.strip().lower())
        .where(ProductFamily.category == category)
        .where(LabelVariant.template_id == template.id)
    )
    candidates = db.execute(query).scalars().all()
    required = set(required_fields)

    for candidate in candidates:
        if mrp is not None and not same_money(candidate.mrp, mrp):
            continue
        if selling_price is not None:
            if not same_money(candidate.selling_price, selling_price):
                continue
        elif candidate.selling_price is not None:
            continue
        if coded_price.strip():
            if not same_text(candidate.coded_price, coded_price):
                continue
        elif candidate.coded_price:
            continue
        if family_name.strip() and not same_text(candidate.family.family_name, family_name):
            continue
        if "brand" in required and brand.strip() and not same_text(candidate.brand, brand):
            continue
        if ("article" in required or "article_no" in required) and article_no.strip() and not same_text(candidate.article_no, article_no):
            continue
        if "size" in required and size.strip() and not same_text(candidate.size, size):
            continue
        if "batch_no" in required and batch_no.strip() and not same_text(candidate.batch_no, batch_no):
            continue
        if "expiry" in required and expiry.strip() and not same_text(candidate.expiry, expiry):
            continue
        candidate_extras = parse_extra_field_values(candidate.extra_field_values)
        extra_mismatch = False
        for field_name, field_value in extra_field_values.items():
            if field_name in required and field_value.strip() and not same_text(candidate_extras.get(field_name), field_value):
                extra_mismatch = True
                break
        if extra_mismatch:
            continue
        return candidate
    return None
