from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PosCart, PosCartItem, Sale, SaleItem


LOCAL_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="IST")


class CheckoutError(RuntimeError):
    def __init__(self, message: str, cart_item_id: int | None = None, field_name: str | None = None):
        super().__init__(message)
        self.cart_item_id = cart_item_id
        self.field_name = field_name


def money(value: Decimal | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def current_bill_year() -> int:
    return datetime.now(LOCAL_TIMEZONE).year


def next_bill_number(db: Session, year: int | None = None) -> str:
    bill_year = year or current_bill_year()
    prefix = f"SB-{bill_year}-"
    existing = db.execute(
        select(Sale.bill_number)
        .where(Sale.bill_number.like(f"{prefix}%"))
        .order_by(Sale.bill_number.desc())
    ).scalars().all()
    sequence = 0
    for bill_number in existing:
        try:
            sequence = max(sequence, int(str(bill_number).removeprefix(prefix)))
        except ValueError:
            continue
    return f"{prefix}{sequence + 1:06d}"


def checkout_cart(
    db: Session,
    cart: PosCart | None,
    *,
    payment_mode: str = "cash",
    notes: str | None = None,
) -> Sale:
    if not cart or cart.status != "active":
        raise CheckoutError("No active cart to checkout.")

def _build_sale_items(db: Session, cart: PosCart) -> tuple[list[SaleItem], Decimal]:
    items = db.execute(
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart.id)
        .order_by(PosCartItem.id)
    ).scalars().all()
    if not items:
        raise CheckoutError("Cart is empty.")

    subtotal = Decimal("0.00")
    sale_items: list[SaleItem] = []
    for item in items:
        variant = item.variant
        is_barcode = bool(variant)
        is_tally = item.source_type == "tally_item" and bool((item.tally_stock_item_name_snapshot or "").strip())
        if item.source_type == "manual" or item.is_manual_line:
            raise CheckoutError("Manual POS lines are not allowed. Select a saved barcode or Tally item.", cart_item_id=item.id, field_name="item")
        if not (is_barcode or is_tally):
            raise CheckoutError("Invalid POS line. Select a saved barcode or Tally item.", cart_item_id=item.id, field_name="item")
        rate = item.rate_snapshot if item.rate_snapshot is not None else item.unit_price
        if rate is None and variant:
            rate = variant.selling_price
        item_name = item.item_name_snapshot or (
            variant.family.family_name if variant and variant.family and variant.family.family_name else variant.item_display_name if variant else ""
        )
        if not item_name:
            raise CheckoutError("Cart contains a line without an item name.", cart_item_id=item.id, field_name="item")
        if rate is None or money(rate) <= 0:
            raise CheckoutError(f"Rate is missing for {item_name}.", cart_item_id=item.id, field_name="rate")
        qty = int(item.qty or 1)
        if qty == 0:
            raise CheckoutError(f"Quantity cannot be zero for {item_name}.", cart_item_id=item.id, field_name="qty")
        amount = money(rate) * qty
        subtotal += amount
        barcode = item.barcode_snapshot if item.barcode_snapshot is not None else variant.barcode if variant else ""
        tally_name = item.tally_stock_item_name_snapshot or (
            variant.family.tally_stock_item_name if variant and variant.family else None
        )
        mrp = item.mrp_snapshot if item.mrp_snapshot is not None else variant.mrp if variant else None
        if mrp is not None and money(mrp) < money(rate):
            raise CheckoutError(f"MRP cannot be lower than Rate for {item_name}.", cart_item_id=item.id, field_name="mrp")
        sale_items.append(
            SaleItem(
                label_variant_id=variant.id if variant else None,
                barcode=barcode or "",
                item_name=item_name,
                tally_stock_item_name=tally_name,
                qty=qty,
                rate=money(rate),
                mrp=mrp,
                discount_amount=Decimal("0.00"),
                amount=amount,
            )
        )
    return sale_items, subtotal


def checkout_cart(
    db: Session,
    cart: PosCart | None,
    *,
    payment_mode: str = "cash",
    notes: str | None = None,
) -> Sale:
    if not cart or cart.status != "active":
        raise CheckoutError("No active cart to checkout.")
    if cart.cart_mode == "sale_edit":
        raise CheckoutError("Cart is in edit mode. Use save_sale_edit_cart instead.")

    sale_items, subtotal = _build_sale_items(db, cart)
    payment = (payment_mode or "cash").strip().lower() or "cash"
    clean_notes = (notes or "").strip() or None

    for _ in range(5):
        sale = Sale(
            bill_number=next_bill_number(db),
            status="completed",
            subtotal=money(subtotal),
            discount_total=Decimal("0.00"),
            round_off=Decimal("0.00"),
            total=money(subtotal),
            payment_mode=payment,
            notes=clean_notes,
            print_status="not_printed",
            tally_sync_status="not_started",
        )
        sale.items = sale_items
        cart.status = "checked_out"
        db.add(sale)
        db.add(cart)
        try:
            db.commit()
            db.refresh(sale)
            return sale
        except IntegrityError:
            db.rollback()
            sale_items = [
                SaleItem(
                    label_variant_id=item.label_variant_id,
                    barcode=item.barcode,
                    item_name=item.item_name,
                    tally_stock_item_name=item.tally_stock_item_name,
                    qty=item.qty,
                    rate=item.rate,
                    mrp=item.mrp,
                    discount_amount=item.discount_amount,
                    amount=item.amount,
                )
                for item in sale_items
            ]
            cart.status = "active"

    raise CheckoutError("Could not generate a unique bill number. Try checkout again.")


def save_sale_edit_cart(
    db: Session,
    cart: PosCart | None,
    *,
    payment_mode: str = "cash",
    notes: str | None = None,
) -> Sale:
    if not cart or cart.status != "active":
        raise CheckoutError("No active cart to checkout.")
    if cart.cart_mode != "sale_edit" or not cart.source_sale_id:
        raise CheckoutError("Cart is not in edit mode.")

    sale = db.get(Sale, cart.source_sale_id)
    if not sale:
        raise CheckoutError("Original sale was not found.")

    sale_items, subtotal = _build_sale_items(db, cart)
    payment = (payment_mode or "cash").strip().lower() or "cash"
    clean_notes = (notes or "").strip() or None

    for existing_item in sale.items:
        db.delete(existing_item)
    
    sale.items = sale_items
    sale.subtotal = money(subtotal)
    sale.total = money(subtotal)
    sale.payment_mode = payment
    sale.notes = clean_notes
    cart.status = "discarded"
    db.add(sale)
    db.add(cart)
    db.commit()
    db.refresh(sale)
    return sale


