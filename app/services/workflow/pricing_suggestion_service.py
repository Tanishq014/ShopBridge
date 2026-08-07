from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PricingRule, ProductFamily
from app.services.settings_service import get_pricing_settings

@dataclass
class PricingSuggestion:
    cost_based_suggestion: Decimal | None
    mrp_based_suggestion: Decimal | None
    cost_rule_type: str | None
    cost_rule_percent: Decimal | None
    mrp_discount_percent: Decimal | None
    unified_suggestion: Decimal | None
    is_conflict: bool


def _apply_rounding(value: Decimal, rounding_mode: int | str | None, truncate_decimal: bool = False) -> Decimal:
    from decimal import ROUND_DOWN
    if truncate_decimal:
        return value.to_integral_value(rounding=ROUND_DOWN)

    if not rounding_mode:
        rounding_mode = 5 # fallback

    try:
        mode = int(rounding_mode)
    except (TypeError, ValueError):
        mode = 5

    if mode == 9:
        val_int = value.to_integral_value(rounding=ROUND_DOWN)
        remainder = val_int % Decimal("10")
        if remainder != Decimal("9"):
            val_int = val_int - remainder + Decimal("9")
        return val_int
    else:
        step = Decimal(str(mode if mode in (1, 5, 10) else 5))
        remainder = value % step
        if remainder > Decimal("0"):
            value = value + (step - remainder)
        if value % Decimal("1") == Decimal("0"):
            return value.to_integral_value(rounding=ROUND_DOWN)
        return value


def get_effective_pricing_rule(db: Session, family: ProductFamily | None) -> tuple[str | None, Decimal | None, Decimal | None]:
    cost_rule_type = None
    cost_rule_percent = None
    mrp_discount_percent = None
    
    global_rule = db.scalar(select(PricingRule).where(PricingRule.category == None))
    cat_rule = None
    if family and family.category:
        cat_rule = db.scalar(select(PricingRule).where(PricingRule.category == family.category))
        
    # MRP Discount independently inherited
    if family and family.mrp_discount_percent is not None:
        mrp_discount_percent = family.mrp_discount_percent
    elif cat_rule and cat_rule.mrp_discount_percent is not None:
        mrp_discount_percent = cat_rule.mrp_discount_percent
    elif global_rule and global_rule.mrp_discount_percent is not None:
        mrp_discount_percent = global_rule.mrp_discount_percent

    # Cost rule independently inherited as a pair
    if family and family.cost_rule_type is not None and family.cost_rule_percent is not None:
        cost_rule_type = family.cost_rule_type
        cost_rule_percent = family.cost_rule_percent
    elif cat_rule and cat_rule.cost_rule_type is not None and cat_rule.cost_rule_percent is not None:
        cost_rule_type = cat_rule.cost_rule_type
        cost_rule_percent = cat_rule.cost_rule_percent
    elif global_rule and global_rule.cost_rule_type is not None and global_rule.cost_rule_percent is not None:
        cost_rule_type = global_rule.cost_rule_type
        cost_rule_percent = global_rule.cost_rule_percent
        
    return cost_rule_type, cost_rule_percent, mrp_discount_percent


def generate_pricing_suggestions(
    db: Session,
    family: ProductFamily | None,
    landing_price: Decimal | None,
    mrp: Decimal | None,
) -> PricingSuggestion:
    cost_rule_type, cost_rule_percent, mrp_discount_percent = get_effective_pricing_rule(db, family)

    cost_based: Decimal | None = None
    if landing_price is not None and landing_price > 0 and cost_rule_percent is not None:
        if cost_rule_type == "MARKUP":
            cost_based = landing_price * (Decimal("1") + cost_rule_percent / Decimal("100"))
        elif cost_rule_type == "GROSS_MARGIN" and cost_rule_percent < Decimal("100"):
            cost_based = landing_price / (Decimal("1") - cost_rule_percent / Decimal("100"))

    mrp_based: Decimal | None = None
    if mrp is not None and mrp > 0 and mrp_discount_percent is not None:
        mrp_based = mrp * (Decimal("1") - mrp_discount_percent / Decimal("100"))

    pricing_settings = get_pricing_settings()
    rounding = pricing_settings.mrp_rounding
    truncate = pricing_settings.mrp_truncate_decimal

    if cost_based is not None:
        cost_based = _apply_rounding(cost_based, rounding, truncate)
    if mrp_based is not None:
        mrp_based = _apply_rounding(mrp_based, rounding, truncate)

    unified: Decimal | None = None
    is_conflict = False

    if cost_based is not None and mrp_based is not None:
        if cost_based == mrp_based:
            unified = cost_based
        else:
            is_conflict = True
    elif cost_based is not None:
        unified = cost_based
    elif mrp_based is not None:
        unified = mrp_based

    return PricingSuggestion(
        cost_based_suggestion=cost_based,
        mrp_based_suggestion=mrp_based,
        cost_rule_type=cost_rule_type,
        cost_rule_percent=cost_rule_percent,
        mrp_discount_percent=mrp_discount_percent,
        unified_suggestion=unified,
        is_conflict=is_conflict,
    )
