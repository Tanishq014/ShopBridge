from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LabelVariant


INTERNAL_BARCODE_START = 240000000001


def normalize_barcode(value: str | None) -> str:
    return (value or "").strip()


def generate_next_barcode(db: Session) -> str:
    barcodes = db.execute(select(LabelVariant.barcode)).scalars().all()
    highest = INTERNAL_BARCODE_START - 1

    for barcode in barcodes:
        if not barcode:
            continue
        clean = barcode.strip()
        if clean.isdigit() and int(clean) >= INTERNAL_BARCODE_START:
            highest = max(highest, int(clean))

    return str(highest + 1)


def barcode_exists(db: Session, barcode: str, exclude_variant_id: int | None = None) -> bool:
    query = select(LabelVariant).where(LabelVariant.barcode == barcode)
    if exclude_variant_id is not None:
        query = query.where(LabelVariant.id != exclude_variant_id)
    return db.scalar(query) is not None


def assign_barcode(
    db: Session,
    requested_barcode: str | None = None,
    exclude_variant_id: int | None = None,
) -> str:
    barcode = normalize_barcode(requested_barcode)
    if barcode:
        if barcode_exists(db, barcode, exclude_variant_id=exclude_variant_id):
            raise ValueError(f"Barcode already exists: {barcode}")
        return barcode

    barcode = generate_next_barcode(db)
    while barcode_exists(db, barcode, exclude_variant_id=exclude_variant_id):
        barcode = str(int(barcode) + 1)
    return barcode

