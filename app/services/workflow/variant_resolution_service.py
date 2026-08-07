from __future__ import annotations

from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.models import LabelVariant, ProductFamily, TemplateMaster
from app.services.barcode_service import assign_barcode
from app.services.workflow.validation_service import label_details_changed
from app.services.workflow.label_draft_service import LabelDraft, draft_to_persistence_adapter

def _resolve_family_for_billing_item(db: Session, billing_item: str) -> ProductFamily:
    clean_name = (billing_item or "").strip()
    families = db.scalars(
        select(ProductFamily)
        .where(ProductFamily.family_name.ilike(clean_name))
        .order_by(desc(ProductFamily.id))
    ).all()
    
    if families:
        return families[0]
        
    new_family = ProductFamily(
        family_name=clean_name,
        category="Uncategorized",
        default_unit="PCS"
    )
    db.add(new_family)
    db.flush()
    return new_family


def resolve_variant_for_receiving(
    db: Session,
    draft: LabelDraft,
    billing_item: str,
    mrp: Decimal | None = None,
    selling_price: Decimal | None = None,
    manual_barcode: str = "",
) -> LabelVariant:
    
    clean_billing = (billing_item or "").strip()
    
    # 1. Translate Draft into LabelVariant identity schema
    core_fields, normalized_extra = draft_to_persistence_adapter(draft, clean_billing)
    
    # Pricing is explicitly authoritative in the DB, regardless of whether the template prints it.
    if mrp is not None:
        core_fields["mrp"] = mrp
    if selling_price is not None:
        core_fields["selling_price"] = selling_price
        
    from app.services.price_code_service import generate_coded_price
    if core_fields["selling_price"]:
        core_fields["coded_price"] = generate_coded_price(core_fields["selling_price"]) or ""
    
    # 2. Search for exact matches across ALL families that share this name
    matched_families = db.scalars(
        select(ProductFamily)
        .where(ProductFamily.family_name.ilike(clean_billing))
    ).all()
    
    if matched_families:
        family_ids = [f.id for f in matched_families]
        all_candidates = db.scalars(
            select(LabelVariant)
            .where(LabelVariant.family_id.in_(family_ids))
            .order_by(desc(LabelVariant.id))
        ).all()
        
        template = db.get(TemplateMaster, draft.template_id) if draft.template_id else None
        
        for candidate in all_candidates:
            changed = label_details_changed(
                candidate,
                category=candidate.family.category or "", # Ignore category changes for identity match if same family name
                family_name=candidate.family.family_name,
                template=template,
                brand=core_fields["brand"],
                item_display_name=core_fields["item_display_name"],
                article_no=core_fields["article_no"],
                size=core_fields["size"],
                batch_no=core_fields["batch_no"],
                expiry=core_fields["expiry"],
                extra_field_values=normalized_extra,
                mrp=core_fields["mrp"],
                selling_price=core_fields["selling_price"],
                coded_price=core_fields["coded_price"],
            )
            if not changed:
                return candidate
                
    # 3. If no match found, deterministically pick the family with highest ID (or create one)
    family = _resolve_family_for_billing_item(db, clean_billing)
    template = db.get(TemplateMaster, draft.template_id) if draft.template_id else None
    
    # Create new barcode and variant
    try:
        final_barcode = assign_barcode(db, manual_barcode.strip(), template=template)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    import json
    new_variant = LabelVariant(
        barcode=final_barcode,
        family_id=family.id,
        item_display_name=core_fields["item_display_name"],
        brand=core_fields["brand"] or None,
        article_no=core_fields["article_no"] or None,
        size=core_fields["size"] or None,
        batch_no=core_fields["batch_no"] or None,
        expiry=core_fields["expiry"] or None,
        mrp=core_fields["mrp"],
        selling_price=core_fields["selling_price"],
        coded_price=core_fields["coded_price"] or None,
        extra_field_values=json.dumps(normalized_extra) if normalized_extra else None,
        template_id=template.id if template else None,
        status="active"
    )
    db.add(new_variant)
    db.flush()
    return new_variant
