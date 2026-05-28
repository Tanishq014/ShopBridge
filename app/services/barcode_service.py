import string

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LabelVariant
from app.services.settings_service import get_barcode_settings


INTERNAL_BARCODE_START = 240000000001
ALPHANUMERIC_ALPHABET = string.digits + string.ascii_uppercase
CATEGORY_PREFIXES = {
    "clothes": "C",
    "cosmetics": "M",
    "gifts": "G",
    "toys": "T",
}


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


def _to_base36(value: int) -> str:
    if value <= 0:
        return "0"
    chars: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        chars.append(ALPHANUMERIC_ALPHABET[remainder])
    return "".join(reversed(chars))


def _short_numeric_candidate(sequence: int, length: int) -> str:
    start = 10 ** (length - 1)
    end = (10 ** length) - 1
    value = start + sequence
    if value > end:
        raise ValueError(f"Short numeric barcode space is full for length {length}.")
    return str(value)


def _short_alphanumeric_candidate(sequence: int, length: int) -> str:
    value = _to_base36(sequence + 1)
    if len(value) > length:
        raise ValueError(f"Short alphanumeric barcode space is full for length {length}.")
    return value.rjust(length, "0")


def _category_prefix_candidate(sequence: int, length: int, category: str | None) -> str:
    prefix = CATEGORY_PREFIXES.get((category or "").strip().lower(), "S")
    digits = max(1, length - len(prefix))
    value = sequence + 1
    if len(str(value)) > digits:
        raise ValueError(f"Category barcode space is full for prefix {prefix}.")
    return f"{prefix}{value:0{digits}d}"


def generate_configured_barcode(db: Session, category: str | None = None) -> str:
    settings = get_barcode_settings()
    if settings.mode == "manual_company_barcode":
        raise ValueError("Enter or scan a company barcode before printing.")

    for sequence in range(0, 10_000_000):
        if settings.mode == "category_prefix":
            barcode = _category_prefix_candidate(sequence, settings.length, category)
        elif settings.mode == "short_alphanumeric":
            barcode = _short_alphanumeric_candidate(sequence, settings.length)
        else:
            barcode = _short_numeric_candidate(sequence, settings.length)
        if not barcode_exists(db, barcode):
            return barcode

    raise ValueError("Could not generate a unique barcode.")


def barcode_exists(db: Session, barcode: str, exclude_variant_id: int | None = None) -> bool:
    query = select(LabelVariant).where(LabelVariant.barcode == barcode)
    if exclude_variant_id is not None:
        query = query.where(LabelVariant.id != exclude_variant_id)
    return db.scalar(query) is not None


def assign_barcode(
    db: Session,
    requested_barcode: str | None = None,
    exclude_variant_id: int | None = None,
    category: str | None = None,
) -> str:
    barcode = normalize_barcode(requested_barcode)
    if barcode:
        if barcode_exists(db, barcode, exclude_variant_id=exclude_variant_id):
            raise ValueError(f"Barcode already exists: {barcode}")
        return barcode

    barcode = generate_configured_barcode(db, category=category)
    while barcode_exists(db, barcode, exclude_variant_id=exclude_variant_id):
        barcode = generate_configured_barcode(db, category=category)
    return barcode
