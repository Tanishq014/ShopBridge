from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ReceivingItem, TemplateMaster, LabelVariant, ProductFamily
from app.services.settings_service import get_template_field_settings
from app.services.field_config import parse_required_fields, normalize_field_name, parse_field_defaults
from app.services.price_code_service import generate_coded_price
from app.services.workflow.form_state_service import parse_extra_field_values
from app.services.workflow.pricing_workflow_service import money, compact_money

UNSAFE_INHERITANCE_FIELDS = {
    "barcode",
    "mrp", "selling_price", "coded_price",
    "item_display_name", "design", "itemname", "item",
    "article", "article_no", "article_number", "articleno",
    "batch", "batch_no", "batchno", "expiry", 
    "serial", "serial_number", "serialno", "srno", "sr_no"
}

@dataclass
class DraftField:
    template_field: str
    semantic_field: str
    value: str | None
    source: str
    required: bool
    missing: bool
    default_value: str | None = None

@dataclass
class LabelDraft:
    template_id: int | None
    ready: bool
    fields: list[DraftField]
    manual_overrides: dict[str, str]


def _get_semantic_mapping(template: TemplateMaster) -> dict[str, str]:
    if not template or not template.semantic_mappings:
        return {}
    try:
        raw_mappings = json.loads(template.semantic_mappings)
        if isinstance(raw_mappings, dict):
            return {
                normalize_field_name(k): normalize_field_name(v) 
                for k, v in raw_mappings.items() 
                if normalize_field_name(k) and normalize_field_name(v)
            }
    except (TypeError, json.JSONDecodeError):
        pass
    return {}


def _find_safe_previous_context(db: Session, item: ReceivingItem) -> dict[str, str]:
    if item.matched_variant_id:
        variant = db.get(LabelVariant, item.matched_variant_id)
        if variant:
            return _variant_to_dict(variant)
            
    if not item.billing_item:
        return {}
        
    normalized_billing = (item.billing_item or "").strip().lower()
    
    # Try to find a recent variant from ANY matching family
    families = db.scalars(
        select(ProductFamily)
        .where(ProductFamily.family_name.ilike(normalized_billing))
    ).all()
    
    if not families:
        return {}
        
    family_ids = [f.id for f in families]
    
    # Find most recent variant across all these families
    latest_variant = db.scalars(
        select(LabelVariant)
        .where(LabelVariant.family_id.in_(family_ids))
        .order_by(desc(LabelVariant.id))
        .limit(1)
    ).first()
    
    if latest_variant:
        return _variant_to_dict(latest_variant)
        
    return {}


def _variant_to_dict(variant: LabelVariant) -> dict[str, str]:
    category = (variant.family.category or "").strip().lower()
    d = {
        "barcode": variant.barcode,
        "family_id": str(variant.family_id),
        "family_name": variant.family.family_name,
        "category": category,
        "brand": variant.brand or "",
        "item_display_name": variant.item_display_name,
        "article_no": variant.article_no or "",
        "article": variant.article_no or "",
        "size": variant.size or "",
        "batch_no": variant.batch_no or "",
        "expiry": variant.expiry or "",
        "mrp": compact_money(variant.mrp),
        "selling_price": money(variant.selling_price),
        "coded_price": variant.coded_price or "",
    }
    
    extra = parse_extra_field_values(variant.extra_field_values)
    for k, v in extra.items():
        if k not in d:
            d[k] = v
            
    return {normalize_field_name(k): str(v).strip() for k, v in d.items() if str(v).strip()}


def resolve_draft(db: Session, item: ReceivingItem, template_id_override: int | None = None) -> LabelDraft:
    tid = template_id_override or item.template_id
    template = db.get(TemplateMaster, tid) if tid else None
    
    if not template:
        return LabelDraft(template_id=None, ready=False, fields=[], manual_overrides={})
        
    required_fields = parse_required_fields(template.required_fields)
    semantic_mappings = _get_semantic_mapping(template)
    
    manual = parse_extra_field_values(item.manual_overrides)
    extracted = parse_extra_field_values(item.extracted_attributes)
    previous = _find_safe_previous_context(db, item)
    defaults = parse_field_defaults(template.default_field_values)
    
    fields = []
    ready = True
    
    # Pre-resolve pricing and billing info
    pricing_context = {}
    if item.mrp is not None:
        pricing_context["mrp"] = compact_money(item.mrp)
    if item.confirmed_selling_price is not None:
        pricing_context["selling_price"] = money(item.confirmed_selling_price)
        pricing_context["coded_price"] = generate_coded_price(item.confirmed_selling_price)
        
    if item.billing_item:
        pricing_context["billing_item"] = item.billing_item
        pricing_context["family_name"] = item.billing_item
        
        
    template_field_settings = get_template_field_settings()
    
    for t_field in required_fields:
        sem_field = semantic_mappings.get(t_field, t_field)
        
        val = None
        source = "MISSING"
        
        # 1. MANUAL
        if sem_field in manual:
            val = manual[sem_field]
            source = "MANUAL"
        # 2. PRICING / BILLING ITEM
        elif sem_field in pricing_context:
            val = pricing_context[sem_field]
            source = "PRICING"
        # 3. EXTRACTED
        elif sem_field in extracted:
            val = extracted[sem_field]
            source = "AI"
        # 4. PREVIOUS
        elif sem_field in previous and sem_field not in UNSAFE_INHERITANCE_FIELDS:
            val = previous[sem_field]
            source = "PREVIOUS"
        # 5. DEFAULT
        # Template sample/dummy values from BarTender files must NEVER contaminate invoice grid cells.
        # The default_value is retained on DraftField for metadata/placeholder only.
            
        is_strictly_required = not template_field_settings.is_optional(sem_field) and sem_field not in ["barcode", "coded_price"]
        
        # A field is considered missing if its final resolved value is empty
        is_empty = not val or not str(val).strip()
        
        if is_empty and is_strictly_required:
            ready = False
            
        fields.append(DraftField(
            template_field=t_field,
            semantic_field=sem_field,
            value=val if not is_empty else None,
            source=source if not is_empty or source == "MANUAL" else "MISSING",
            required=is_strictly_required,
            missing=is_empty if is_strictly_required else False,
            default_value=defaults.get(t_field)
        ))
        
    return LabelDraft(
        template_id=template.id,
        ready=ready,
        fields=fields,
        manual_overrides=manual
    )

def draft_to_persistence_adapter(draft: LabelDraft, billing_item: str) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Converts a LabelDraft into the core fields + normalized extra_field_values
    required for structural parity with New Stock's LabelVariant storage.
    """
    core_fields = {
        "brand": "",
        "article_no": "",
        "size": "",
        "batch_no": "",
        "expiry": "",
        "mrp": None,
        "selling_price": None,
        "coded_price": "",
    }
    
    # Check if template actually defines an item display name / design field
    template_has_item_field = any(
        f.semantic_field in ("item_display_name", "design", "itemname", "item")
        for f in draft.fields
    )
    item_display_name = ""
    
    extra_values = {}
    
    # To determine standard fields, we use normalized field mappings as New Stock does.
    for f in draft.fields:
        if f.missing or f.value is None:
            continue
            
        sem = f.semantic_field
        val = str(f.value).strip()
        
        if sem == "brand":
            core_fields["brand"] = val
        elif sem in ("article", "article_no"):
            core_fields["article_no"] = val
        elif sem == "size":
            core_fields["size"] = val
        elif sem in ("batch_no", "batch"):
            core_fields["batch_no"] = val
        elif sem == "expiry":
            core_fields["expiry"] = val
        elif sem == "mrp":
            from app.services.workflow.validation_service import decimal_or_none
            core_fields["mrp"] = decimal_or_none(val)
        elif sem == "selling_price":
            from app.services.workflow.validation_service import decimal_or_none
            core_fields["selling_price"] = decimal_or_none(val)
        elif sem == "coded_price":
            core_fields["coded_price"] = val
        elif sem in ("item_display_name", "design", "itemname", "item"):
            item_display_name = val
        elif sem in ("billing_item", "family_name"):
            pass # handled explicitly
        else:
            # Must go to extra_field_values. 
            extra_values[f.template_field] = val
            
    # The adapter GUARANTEES structural parity by parsing the extra values again.
    normalized_extra = parse_extra_field_values(json.dumps(extra_values))
    
    # If the template requires/contains item_display_name but no explicit value was given, fall back to billing_item.
    # If the template does not contain item_display_name (like Small 1, Small 2), leave it empty to match New Stock.
    if template_has_item_field and not item_display_name:
        item_display_name = billing_item
        
    core_fields["item_display_name"] = item_display_name
    
    return core_fields, normalized_extra
