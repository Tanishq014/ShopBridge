from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LabelVariant
from app.services.barcode_service import normalize_barcode


def lookup_saved_price_by_barcode(db: Session, barcode: str) -> LabelVariant | None:
    clean_barcode = normalize_barcode(barcode)
    if not clean_barcode:
        return None
    return db.scalar(
        select(LabelVariant)
        .where(LabelVariant.barcode == clean_barcode)
        .where(LabelVariant.status == "active")
    )
