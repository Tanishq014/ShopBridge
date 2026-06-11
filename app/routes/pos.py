from __future__ import annotations

import logging
import time
from io import BytesIO
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import LabelVariant, PosCart, PosCartItem, ProductFamily, Sale, TallyItem
from app.services.barcode_service import normalize_barcode
from app.services.billing_service import lookup_saved_price_by_barcode
from app.services.network_service import phone_print_url, qr_url_for_phone_print, qr_url_for_scanner, scanner_url
from app.services.sales_service import CheckoutError, checkout_cart
from app.services.settings_service import get_upi_settings
from app.services.template_filters import register_template_filters
from app.services.time_service import LOCAL_TIMEZONE


router = APIRouter(tags=["pos"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))
logger = logging.getLogger(__name__)
_pos_cart_heartbeat: dict[str, object] = {
    "signature": None,
    "last_log_at": 0.0,
}
ACTIVE_CART_STATUS = "active"
HELD_CART_STATUS = "held"
DISCARDED_CART_STATUS = "discarded"
NORMAL_CART_MODE = "normal"
SALE_COPY_CART_MODE = "sale_copy"
SALE_EDIT_CART_MODE = "sale_edit"
ALLOWED_PAYMENT_MODES = {"cash", "upi", "card"}


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    clean = str(value).strip()
    if not clean:
        return None
    try:
        return Decimal(clean).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid rate.")


def _line_rate(item: PosCartItem) -> Decimal | None:
    if item.rate_snapshot is not None:
        return item.rate_snapshot
    if item.unit_price is not None:
        return item.unit_price
    return item.variant.selling_price if item.variant else None


def _line_mrp(item: PosCartItem) -> Decimal | None:
    if item.mrp_snapshot is not None:
        return item.mrp_snapshot
    return item.variant.mrp if item.variant else None


def _line_barcode(item: PosCartItem) -> str:
    if item.barcode_snapshot is not None:
        return item.barcode_snapshot
    return item.variant.barcode if item.variant else ""


def _line_item_name(item: PosCartItem) -> str:
    if item.item_name_snapshot:
        return item.item_name_snapshot
    variant = item.variant
    if variant and variant.family and variant.family.family_name:
        return variant.family.family_name
    return variant.item_display_name if variant else ""


def _line_tally_name(item: PosCartItem) -> str:
    if item.tally_stock_item_name_snapshot:
        return item.tally_stock_item_name_snapshot
    variant = item.variant
    return variant.family.tally_stock_item_name if variant and variant.family and variant.family.tally_stock_item_name else ""


def _find_active_cart(db: Session, *, normalize_duplicates: bool = False) -> PosCart | None:
    active_carts = db.execute(
        select(PosCart)
        .where(PosCart.status == ACTIVE_CART_STATUS)
        .order_by(PosCart.id.desc())
    ).scalars().all()
    if not active_carts:
        return None

    current = active_carts[0]
    if len(active_carts) == 1 or not normalize_duplicates:
        return current

    for stale_cart in active_carts[1:]:
        if stale_cart.cart_mode == NORMAL_CART_MODE and _cart_has_items(db, stale_cart):
            stale_cart.status = HELD_CART_STATUS
        else:
            stale_cart.status = DISCARDED_CART_STATUS
        db.add(stale_cart)
    db.commit()
    db.refresh(current)
    logger.warning(
        "Normalized %s duplicate active POS carts; keeping cart %s.",
        len(active_carts) - 1,
        current.id,
    )
    return current


def _active_cart(db: Session) -> PosCart:
    cart = _find_active_cart(db, normalize_duplicates=True)
    if cart:
        return cart
    cart = PosCart(status=ACTIVE_CART_STATUS, cart_mode=NORMAL_CART_MODE)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


def _cart_items(db: Session, cart: PosCart) -> list[PosCartItem]:
    return db.execute(
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart.id)
        .order_by(PosCartItem.id)
    ).scalars().all()


def _cart_has_items(db: Session, cart: PosCart) -> bool:
    return db.scalar(
        select(func.count(PosCartItem.id)).where(PosCartItem.cart_id == cart.id)
    ) > 0


def _park_active_cart(db: Session, *, discard_empty: bool = True) -> PosCart | None:
    cart = _find_active_cart(db, normalize_duplicates=True)
    if not cart:
        return None

    if cart.cart_mode == SALE_COPY_CART_MODE:
        cart.status = DISCARDED_CART_STATUS
        db.add(cart)
        return None

    if cart.cart_mode == SALE_EDIT_CART_MODE:
        cart.status = DISCARDED_CART_STATUS
        db.add(cart)
        return None

    if cart.cart_mode == NORMAL_CART_MODE and _cart_has_items(db, cart):
        cart.status = HELD_CART_STATUS
        db.add(cart)
        return cart

    if discard_empty:
        cart.status = DISCARDED_CART_STATUS
        db.add(cart)
    return None


def _held_cart_payload(db: Session, cart: PosCart) -> dict[str, object]:
    payload = _cart_payload(db, cart)
    bill_number = None
    if cart.cart_mode == SALE_EDIT_CART_MODE and cart.source_sale_id:
        source_sale = db.get(Sale, cart.source_sale_id)
        if source_sale:
            bill_number = source_sale.bill_number
            
    return {
        "id": cart.id,
        "label": f"Held #{cart.id}",
        "status": cart.status,
        "cart_mode": cart.cart_mode,
        "source_sale_id": cart.source_sale_id,
        "bill_number": bill_number,
        "updated_at": cart.updated_at.isoformat() if cart.updated_at else "",
        "created_at": cart.created_at.isoformat() if cart.created_at else "",
        "count": payload["count"],
        "lines": len(payload["items"]),
        "total": payload["total"],
    }


def _held_carts_payload(db: Session) -> list[dict[str, object]]:
    carts = db.execute(
        select(PosCart)
        .where(PosCart.status == HELD_CART_STATUS)
        .order_by(PosCart.id.desc())
    ).scalars().all()
    return [_held_cart_payload(db, cart) for cart in carts if _cart_has_items(db, cart)]


def _active_cart_item_or_error(db: Session, item_id: int) -> PosCartItem | JSONResponse:
    active_cart = _find_active_cart(db, normalize_duplicates=True)
    item = db.get(PosCartItem, item_id)
    if (
        not item
        or not item.cart
        or item.cart.status != ACTIVE_CART_STATUS
        or not active_cart
        or item.cart_id != active_cart.id
    ):
        return _json_error("Cart item was not found.", status_code=404, status="not_found")
    return item


def _apply_variant_to_cart_item(item: PosCartItem, variant: LabelVariant, preserve_values: bool = False) -> None:
    item.variant = variant
    item.variant_id = variant.id
    item.unit_price = variant.selling_price
    item.item_name_snapshot = variant.family.family_name if variant.family else variant.item_display_name
    item.barcode_snapshot = variant.barcode
    item.tally_stock_item_name_snapshot = variant.family.tally_stock_item_name if variant.family else None
    
    if not preserve_values:
        item.mrp_snapshot = variant.mrp
        item.rate_snapshot = variant.selling_price
    else:
        if variant.mrp is not None:
            item.mrp_snapshot = variant.mrp
        if variant.selling_price is not None:
            item.rate_snapshot = variant.selling_price
            
    item.source_type = "barcode"
    item.is_manual_line = False


def _apply_tally_item_to_cart_item(item: PosCartItem, tally_item: TallyItem, preserve_values: bool = False) -> None:
    item_name = tally_item.name or "Tally item"
    tally_name = tally_item.name or item_name
    item.variant = None
    item.variant_id = None
    item.unit_price = None
    item.item_name_snapshot = item_name
    item.barcode_snapshot = ""
    item.tally_stock_item_name_snapshot = tally_name
    
    if not preserve_values:
        item.mrp_snapshot = None
        item.rate_snapshot = None
        
    item.source_type = "tally_item"
    item.is_manual_line = False


def _apply_manual_to_cart_item(
    item: PosCartItem,
    *,
    item_name: str,
    mrp: Decimal | None = None,
    rate: Decimal | None = None,
) -> None:
    item.variant_id = None
    item.unit_price = rate
    item.item_name_snapshot = item_name
    item.barcode_snapshot = ""
    item.tally_stock_item_name_snapshot = ""
    item.mrp_snapshot = mrp
    item.rate_snapshot = rate
    item.source_type = "manual"
    item.is_manual_line = True


def _cart_item_payload(item: PosCartItem) -> dict[str, object]:
    variant = item.variant
    rate = _line_rate(item)
    mrp = _line_mrp(item)
    barcode = _line_barcode(item)
    item_name = _line_item_name(item)
    tally_name = _line_tally_name(item)
    billing_item = variant.family.family_name if variant and variant.family else ""
    category = variant.family.category if variant and variant.family else ""
    template_name = variant.template.template_name if variant and variant.template else ""
    amount = rate * item.qty if rate is not None else None
    source_type = item.source_type or ("barcode" if variant else "tally_item")
    return {
        "id": item.id,
        "variant_id": item.variant_id,
        "barcode": barcode,
        "billing_item": item_name or billing_item,
        "sticker_name": variant.item_display_name if variant else "",
        "item_name": item_name,
        "article_no": variant.article_no or "" if variant else "",
        "brand": variant.brand or "" if variant else "",
        "category": category or "",
        "family_name": item_name or billing_item,
        "tally_stock_item_name": tally_name,
        "template_name": template_name or "",
        "mrp": _money(mrp),
        "selling_price": _money(rate),
        "coded_price": variant.coded_price or "" if variant else "",
        "qty": item.qty,
        "amount": _money(amount),
        "missing_price": rate is None or rate <= 0,
        "source_type": source_type,
        "is_manual_line": bool(item.is_manual_line),
    }


def _empty_cart_payload() -> dict[str, object]:
    return {
        "cart_id": None,
        "status": ACTIVE_CART_STATUS,
        "cart_mode": NORMAL_CART_MODE,
        "source_sale_id": None,
        "items": [],
        "total": "0.00",
        "count": 0,
    }


def _cart_payload(db: Session, cart: PosCart | None = None) -> dict[str, object]:
    cart = cart or _find_active_cart(db)
    if not cart:
        return _empty_cart_payload()
    items = _cart_items(db, cart)
    total = Decimal("0")
    rows = []
    for item in items:
        rows.append(_cart_item_payload(item))
        rate = _line_rate(item)
        if rate is not None:
            total += rate * item.qty
    source_bill_number = None
    if cart.source_sale_id:
        sale = db.get(Sale, cart.source_sale_id)
        if sale:
            source_bill_number = sale.bill_number

    return {
        "cart_id": cart.id,
        "status": cart.status,
        "cart_mode": cart.cart_mode or NORMAL_CART_MODE,
        "source_sale_id": cart.source_sale_id,
        "source_bill_number": source_bill_number,
        "items": rows,
        "total": _money(total),
        "count": sum(item.qty for item in items),
    }


def _json_error(message: str, *, status_code: int, status: str, **extra: object) -> JSONResponse:
    payload = {"ok": False, "status": status, "message": message}
    payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


def _variant_search_payload(variant: LabelVariant, *, exact_barcode: bool = False) -> dict[str, object]:
    family = variant.family
    return {
        "result_type": "barcode",
        "id": variant.id,
        "barcode": variant.barcode,
        "billing_item": family.family_name if family else "",
        "sticker_name": variant.item_display_name,
        "family_name": family.family_name if family else "",
        "item_name": family.family_name if family else variant.item_display_name,
        "article_no": variant.article_no or "",
        "brand": variant.brand or "",
        "category": family.category if family else "",
        "tally_stock_item_name": family.tally_stock_item_name if family else "",
        "mrp": _money(variant.mrp),
        "selling_price": _money(variant.selling_price),
        "coded_price": variant.coded_price or "",
        "missing_price": variant.selling_price is None,
        "exact_barcode": exact_barcode,
    }


def _family_search_payload(family: ProductFamily) -> dict[str, object]:
    display_name = family.family_name or family.tally_stock_item_name or ""
    return {
        "result_type": "family",
        "id": family.id,
        "barcode": "",
        "billing_item": display_name,
        "sticker_name": "",
        "family_name": display_name,
        "item_name": display_name,
        "article_no": "",
        "brand": "",
        "category": family.category or "",
        "tally_stock_item_name": family.tally_stock_item_name or display_name,
        "mrp": "",
        "selling_price": "",
        "coded_price": "",
        "missing_price": True,
        "exact_barcode": False,
    }


@router.get("/pos", response_class=HTMLResponse)
def pos_page(
    request: Request,
    checkout_error: str | None = None,
    sale_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    scanner, detected = scanner_url(request.headers.get("host"))
    phone_print, phone_print_detected = phone_print_url(request.headers.get("host"))
    return templates.TemplateResponse(
        request,
        "pos.html",
        {
            "request": request,
            "scanner_url": scanner,
            "scanner_qr_url": qr_url_for_scanner(scanner),
            "scanner_ip_detected": detected,
            "phone_print_url": phone_print,
            "phone_print_qr_url": qr_url_for_phone_print(phone_print),
            "phone_print_ip_detected": phone_print_detected,
            "error": checkout_error,
            "initial_sale_id": sale_id,
            "held_carts": _held_carts_payload(db),
            "upi_settings": __import__("dataclasses").asdict(get_upi_settings()),
        },
    )


@router.get("/scanner", response_class=HTMLResponse)
def scanner_page(request: Request):
    return templates.TemplateResponse(
        request,
        "scanner.html",
        {"request": request},
    )


@router.get("/scanner/qr.svg")
def scanner_qr(url: str):
    try:
        import qrcode
        import qrcode.image.svg
    except Exception:
        return Response("QR generator dependency is not installed. Run pip install -r requirements.txt.", status_code=503)
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    output = BytesIO()
    image.save(output)
    return Response(output.getvalue(), media_type="image/svg+xml")


@router.get("/pos/cart")
def pos_cart(db: Session = Depends(get_db)):
    payload = _cart_payload(db)
    signature = (
        payload.get("cart_id"),
        payload.get("count"),
        payload.get("total"),
        len(payload.get("items", [])),
    )
    now = time.monotonic()
    last_signature = _pos_cart_heartbeat.get("signature")
    last_log_at = float(_pos_cart_heartbeat.get("last_log_at") or 0.0)
    if signature != last_signature or now - last_log_at >= 15:
        logger.info(
            "POS cart heartbeat: cart=%s items=%s total=%s",
            payload.get("cart_id") or "empty",
            payload.get("count") or 0,
            payload.get("total") or "0.00",
        )
        _pos_cart_heartbeat["signature"] = signature
        _pos_cart_heartbeat["last_log_at"] = now
    return payload


@router.get("/pos/cart/held")
def list_held_carts(db: Session = Depends(get_db)):
    items = _held_carts_payload(db)
    for item in items:
        item["type"] = "held"
    return {"ok": True, "items": items}


@router.get("/pos/recent-sales")
def list_recent_sales(offset: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    sales = db.scalars(
        select(Sale)
        .options(selectinload(Sale.items))
        .order_by(Sale.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    # Only exclude sales that have a HELD sale_edit cart pointing at them.
    # These appear in the Held section instead, so showing them in Previous Bills too
    # would create a duplicate entry.
    # Do NOT exclude the sale that is currently being actively edited; it must stay
    # in Previous Bills so PgDown navigation can track position correctly and the
    # blue .opened border indicator works.
    held_edit_sale_ids: set[int] = set(
        db.scalars(
            select(PosCart.source_sale_id)
            .where(
                PosCart.status == HELD_CART_STATUS,
                PosCart.cart_mode == SALE_EDIT_CART_MODE,
                PosCart.source_sale_id.is_not(None),
            )
        ).all()
    )

    items = []
    for sale in sales:
        if sale.id in held_edit_sale_ids:
            continue  # shown in Held section instead
        items.append({
            "type": "sale",
            "id": sale.id,
            "bill_number": sale.bill_number,
            "total": str(sale.total),
            "item_count": len(sale.items),
            "total_qty": sum(item.qty for item in sale.items),
            "created_at": sale.created_at.isoformat() + "Z" if sale.created_at else "",
        })
    return {"ok": True, "items": items, "has_more": len(sales) == limit}


@router.post("/pos/cart/hold")
def hold_active_cart(db: Session = Depends(get_db)):
    cart = _find_active_cart(db, normalize_duplicates=True)
    if not cart or not _cart_has_items(db, cart):
        return _json_error("No active bill to hold.", status_code=400, status="empty")
    if cart.cart_mode == SALE_COPY_CART_MODE:
        return _json_error("Opened saved bill copies cannot be held.", status_code=400, status="sale_copy")
    cart.status = HELD_CART_STATUS
    db.add(cart)
    db.commit()
    return {
        "ok": True,
        "status": "held",
        "message": "Bill held.",
        "held": _held_cart_payload(db, cart),
        "cart": _empty_cart_payload(),
        "held_carts": _held_carts_payload(db),
    }


@router.post("/pos/cart/held/{cart_id}/resume")
def resume_held_cart(
    cart_id: int,
    discard_active: bool = Query(False),
    db: Session = Depends(get_db),
):
    cart = db.get(PosCart, cart_id)
    if not cart or cart.status != HELD_CART_STATUS:
        return _json_error("Held bill was not found.", status_code=404, status="not_found")

    active = _find_active_cart(db, normalize_duplicates=True)
    if active and active.id != cart.id:
        if discard_active:
            active.status = DISCARDED_CART_STATUS
            db.add(active)
        else:
            _park_active_cart(db)

    cart.status = ACTIVE_CART_STATUS
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return {
        "ok": True,
        "status": "resumed",
        "message": "Held bill resumed.",
        "cart": _cart_payload(db, cart),
        "held_carts": _held_carts_payload(db),
    }


@router.post("/pos/cart/held/{cart_id}/discard")
def discard_held_cart(cart_id: int, db: Session = Depends(get_db)):
    cart = db.get(PosCart, cart_id)
    if not cart or cart.status != HELD_CART_STATUS:
        return _json_error("Held bill was not found.", status_code=404, status="not_found")
    cart.status = DISCARDED_CART_STATUS
    db.add(cart)
    db.commit()
    _find_active_cart(db, normalize_duplicates=True)
    return {
        "ok": True,
        "status": "discarded",
        "message": "Held bill discarded.",
        "cart": _cart_payload(db),
        "held_carts": _held_carts_payload(db),
    }


@router.post("/pos/cart/active/discard")
def discard_active_cart(db: Session = Depends(get_db)):
    """Discard the active cart and return a fresh empty cart payload."""
    cart = _find_active_cart(db, normalize_duplicates=True)
    if cart:
        cart.status = DISCARDED_CART_STATUS
        db.add(cart)
        db.commit()
    # Always return a fresh cart so the frontend has a valid cart_id to work with.
    new_cart = PosCart(status=ACTIVE_CART_STATUS, cart_mode=NORMAL_CART_MODE)
    db.add(new_cart)
    db.commit()
    db.refresh(new_cart)
    return {
        "ok": True,
        "status": "discarded",
        "message": "Active bill discarded.",
        "cart": _cart_payload(db, new_cart),
        "held_carts": _held_carts_payload(db),
    }


@router.post("/pos/cart/load-sale/{sale_id}")
def load_sale_into_pos_cart(sale_id: int, db: Session = Depends(get_db)):
    sale = db.scalar(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(Sale.id == sale_id)
    )
    if not sale:
        return _json_error("Saved bill was not found.", status_code=404, status="not_found")

    active = _find_active_cart(db, normalize_duplicates=True)
    if (
        active
        and active.cart_mode == SALE_COPY_CART_MODE
        and active.source_sale_id == sale.id
    ):
        return {
            "ok": True,
            "status": "loaded",
            "message": "Saved bill is already open in POS.",
            "source_sale_id": sale.id,
            "bill_number": sale.bill_number,
            "held_active_cart_id": None,
            "cart": _cart_payload(db, active),
            "held_carts": _held_carts_payload(db),
        }

    held_active = _park_active_cart(db)
    cart = PosCart(status=ACTIVE_CART_STATUS, cart_mode=SALE_COPY_CART_MODE, source_sale_id=sale.id)
    db.add(cart)
    db.flush()

    for sale_item in sale.items:
        rate = sale_item.rate
        source_type = "barcode" if sale_item.label_variant_id else "tally_item"
        is_manual_line = False
        if not sale_item.label_variant_id and not (sale_item.tally_stock_item_name or "").strip():
            source_type = "manual"
            is_manual_line = True
        cart_item = PosCartItem(
            cart_id=cart.id,
            variant_id=sale_item.label_variant_id,
            qty=sale_item.qty,
            unit_price=rate,
            item_name_snapshot=sale_item.item_name,
            barcode_snapshot=sale_item.barcode or "",
            tally_stock_item_name_snapshot=sale_item.tally_stock_item_name,
            mrp_snapshot=sale_item.mrp,
            rate_snapshot=rate,
            source_type=source_type,
            is_manual_line=is_manual_line,
        )
        db.add(cart_item)

    db.commit()
    db.refresh(cart)
    return {
        "ok": True,
        "status": "loaded",
        "message": "Saved bill copied into POS.",
        "source_sale_id": sale.id,
        "bill_number": sale.bill_number,
        "held_active_cart_id": held_active.id if held_active else None,
        "cart": _cart_payload(db, cart),
        "held_carts": _held_carts_payload(db),
    }


@router.post("/pos/cart/load-sale/{sale_id}/edit")
def load_sale_for_edit_in_pos_cart(sale_id: int, db: Session = Depends(get_db)):
    sale = db.scalar(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(Sale.id == sale_id)
    )
    if not sale:
        return _json_error("Saved bill was not found.", status_code=404, status="not_found")

    active = _find_active_cart(db, normalize_duplicates=True)
    if (
        active
        and active.cart_mode == SALE_EDIT_CART_MODE
        and active.source_sale_id == sale.id
    ):
        return {
            "ok": True,
            "status": "loaded",
            "message": "Saved bill is already open for editing.",
            "source_sale_id": sale.id,
            "bill_number": sale.bill_number,
            "held_active_cart_id": None,
            "cart": _cart_payload(db, active),
            "held_carts": _held_carts_payload(db),
        }

    # If this sale is already held for editing, resume that held cart instead of
    # creating a duplicate. This is the case when user held a sale_edit and then
    # navigates to the same sale via PgDown.
    held_edit_cart = db.scalar(
        select(PosCart)
        .where(
            PosCart.status == HELD_CART_STATUS,
            PosCart.cart_mode == SALE_EDIT_CART_MODE,
            PosCart.source_sale_id == sale.id,
        )
        .order_by(PosCart.id.desc())
    )
    if held_edit_cart:
        # Park whatever is currently active, then resume the held edit cart.
        if active and active.id != held_edit_cart.id:
            if active.cart_mode == NORMAL_CART_MODE and _cart_has_items(db, active):
                active.status = HELD_CART_STATUS
                db.add(active)
            else:
                active.status = DISCARDED_CART_STATUS
                db.add(active)
        held_edit_cart.status = ACTIVE_CART_STATUS
        db.add(held_edit_cart)
        db.commit()
        db.refresh(held_edit_cart)
        return {
            "ok": True,
            "status": "loaded",
            "message": "Resumed held edit for this bill.",
            "source_sale_id": sale.id,
            "bill_number": sale.bill_number,
            "held_active_cart_id": None,
            "cart": _cart_payload(db, held_edit_cart),
            "held_carts": _held_carts_payload(db),
        }

    held_active = _park_active_cart(db)
    cart = PosCart(status=ACTIVE_CART_STATUS, cart_mode=SALE_EDIT_CART_MODE, source_sale_id=sale.id)
    db.add(cart)
    db.flush()

    for sale_item in sale.items:
        rate = sale_item.rate
        source_type = "barcode" if sale_item.label_variant_id else "tally_item"
        is_manual_line = False
        if not sale_item.label_variant_id and not (sale_item.tally_stock_item_name or "").strip():
            source_type = "manual"
            is_manual_line = True
        cart_item = PosCartItem(
            cart_id=cart.id,
            variant_id=sale_item.label_variant_id,
            qty=sale_item.qty,
            unit_price=rate,
            item_name_snapshot=sale_item.item_name,
            barcode_snapshot=sale_item.barcode or "",
            tally_stock_item_name_snapshot=sale_item.tally_stock_item_name,
            mrp_snapshot=sale_item.mrp,
            rate_snapshot=rate,
            source_type=source_type,
            is_manual_line=is_manual_line,
        )
        db.add(cart_item)

    db.commit()
    db.refresh(cart)
    return {
        "ok": True,
        "status": "loaded",
        "message": "Original bill loaded for editing.",
        "source_sale_id": sale.id,
        "bill_number": sale.bill_number,
        "held_active_cart_id": held_active.id if held_active else None,
        "cart": _cart_payload(db, cart),
        "held_carts": _held_carts_payload(db),
    }


@router.get("/pos/search")
def pos_search(q: str = Query("", max_length=120), db: Session = Depends(get_db)):
    term = (q or "").strip()
    if not term:
        return {"ok": True, "items": []}

    lowered = term.lower()
    like = f"%{lowered}%"
    clean_barcode = normalize_barcode(term)
    barcode_like = bool(clean_barcode) and len(clean_barcode) >= 4 and clean_barcode.replace("-", "").isalnum()
    variants = db.execute(
        select(LabelVariant)
        .outerjoin(LabelVariant.family)
        .options(joinedload(LabelVariant.family))
        .where(LabelVariant.status == "active")
        .where(
            or_(
                LabelVariant.barcode == clean_barcode,
                func.lower(LabelVariant.barcode).like(like),
                func.lower(LabelVariant.item_display_name).like(like),
                func.lower(LabelVariant.article_no).like(like),
                func.lower(LabelVariant.brand).like(like),
                func.lower(ProductFamily.family_name).like(like),
                func.lower(ProductFamily.tally_stock_item_name).like(like),
            )
        )
        .order_by(LabelVariant.updated_at.desc(), LabelVariant.id.desc())
        .limit(40)
    ).scalars().all()
    def rank(variant: LabelVariant) -> tuple[int, str]:
        exact_barcode = clean_barcode and variant.barcode == clean_barcode
        barcode_start = clean_barcode and variant.barcode and variant.barcode.startswith(clean_barcode)
        starts = any(
            (value or "").lower().startswith(lowered)
            for value in (
                variant.item_display_name,
                variant.article_no,
                variant.brand,
                variant.family.family_name if variant.family else "",
            )
        )
        return (
            0 if exact_barcode else 1 if barcode_start else 2 if starts else 3,
            variant.item_display_name.lower(),
        )

    variants.sort(key=rank)

    variant_results = [
        _variant_search_payload(variant, exact_barcode=bool(clean_barcode and variant.barcode == clean_barcode))
        for variant in variants[:12]
    ]

    tally_items = db.execute(
        select(TallyItem)
        .where(TallyItem.active_status == "active")
        .where(
            or_(
                func.lower(TallyItem.name).like(like),
                func.lower(TallyItem.aliases).like(like)
            )
        )
        .order_by(TallyItem.updated_at.desc(), TallyItem.id.desc())
        .limit(40)
    ).scalars().all()

    def tally_rank(item: TallyItem) -> tuple[int, str]:
        starts = (item.name or "").lower().startswith(lowered)
        alias_starts = (item.aliases or "").lower().startswith(lowered)
        return (1 if (starts or alias_starts) else 3, (item.name or "").lower())

    tally_items.sort(key=tally_rank)
    tally_results = [
        {
            "id": item.id,
            "source_type": "tally_item",
            "tally_item_id": item.id,
            "label": item.name,
            "name": item.name,
            "barcode": "",
            "item_name": item.name,
            "result_type": "tally_item",
        }
        for item in tally_items[:12]
    ]

    if barcode_like:
        results = variant_results + tally_results
    else:
        exact_results = [result for result in variant_results if result["exact_barcode"]]
        non_exact_variants = [result for result in variant_results if not result["exact_barcode"]]
        results = exact_results + non_exact_variants + tally_results
    return {
        "ok": True,
        "items": results[:12],
    }


@router.post("/pos/checkout")
def pos_checkout(
    payment_mode: str = Form("cash"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    payment = (payment_mode or "cash").strip().lower() or "cash"
    if payment not in ALLOWED_PAYMENT_MODES:
        return RedirectResponse(f"/pos?{urlencode({'checkout_error': 'Choose Cash, UPI, or Card payment.'})}", status_code=303)
    cart = _find_active_cart(db, normalize_duplicates=True)
    if not cart:
        return RedirectResponse(f"/pos?{urlencode({'checkout_error': 'No active cart to checkout.'})}", status_code=303)
    try:
        if cart.cart_mode == "sale_edit":
            from app.services.sales_service import save_sale_edit_cart
            sale = save_sale_edit_cart(db, cart, payment_mode=payment, notes=notes)
        else:
            sale = checkout_cart(db, cart, payment_mode=payment, notes=notes)
    except CheckoutError as exc:
        return RedirectResponse(f"/pos?{urlencode({'checkout_error': str(exc)})}", status_code=303)
    return RedirectResponse(f"/sales/{sale.id}", status_code=303)


@router.post("/pos/checkout/json")
async def pos_checkout_json(
    request: Request,
    db: Session = Depends(get_db)
):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    payment = (payload.get("payment_mode") or "cash").strip().lower() or "cash"
    notes = str(payload.get("notes") or "").strip()
    upi_vpa = str(payload.get("upi_vpa") or "").strip()

    if upi_vpa and upi_vpa != "cash":
        payment = "upi"
        from app.services.settings_service import get_upi_settings
        upi_settings = get_upi_settings()
        valid_vpas = {v.strip() for v in (upi_settings.vpa_1, upi_settings.vpa_2, upi_settings.default_vpa) if v.strip()}
        if upi_vpa not in valid_vpas:
            upi_vpa = ""
            payment = "cash"
    else:
        upi_vpa = ""
        payment = "cash"

    if payment not in ALLOWED_PAYMENT_MODES:
        return _json_error("Choose Cash, UPI, or Card payment.", status_code=400, status="invalid_payment")
    cart = _find_active_cart(db, normalize_duplicates=True)
    if not cart:
        return _json_error("No active cart to checkout.", status_code=400, status="empty_cart")
    try:
        if cart.cart_mode == "sale_edit":
            from app.services.sales_service import save_sale_edit_cart
            sale = save_sale_edit_cart(db, cart, payment_mode=payment, notes=notes, upi_vpa=upi_vpa)
        else:
            sale = checkout_cart(db, cart, payment_mode=payment, notes=notes, upi_vpa=upi_vpa)
    except CheckoutError as exc:
        extra = {}
        if exc.cart_item_id is not None:
            extra["cart_item_id"] = exc.cart_item_id
        if exc.field_name is not None:
            extra["field_name"] = exc.field_name
        return _json_error(str(exc), status_code=400, status="checkout_error", **extra)
    return {
        "ok": True,
        "sale_id": sale.id,
        "bill_number": sale.bill_number
    }


@router.post("/pos/scan")
async def pos_scan(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    barcode = normalize_barcode(str(payload.get("barcode", "")))
    allow_missing_price = bool(payload.get("allow_missing_price"))
    if not barcode:
        return _json_error("Enter or scan a barcode.", status_code=400, status="empty")

    variant = lookup_saved_price_by_barcode(db, barcode)
    if not variant:
        return _json_error(
            "Barcode not found.",
            status_code=404,
            status="not_found",
            barcode=barcode,
        )

    if variant.selling_price is None and not allow_missing_price:
        return _json_error(
            "Selling price is missing. Confirm manually before adding this item.",
            status_code=409,
            status="missing_price",
            barcode=barcode,
            item_name=variant.family.family_name if variant.family else variant.item_display_name,
            mrp=_money(variant.mrp),
            coded_price=variant.coded_price or "",
        )

    cart = _active_cart(db)
    is_update = False
    item = db.scalar(
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart.id)
        .where(PosCartItem.variant_id == variant.id)
        .where(PosCartItem.qty > 0)
    )
    if item:
        item.qty += 1
        is_update = True
        item.item_name_snapshot = item.item_name_snapshot or (variant.family.family_name if variant.family else variant.item_display_name)
        item.barcode_snapshot = item.barcode_snapshot or variant.barcode
        item.tally_stock_item_name_snapshot = item.tally_stock_item_name_snapshot or (
            variant.family.tally_stock_item_name if variant.family else None
        )
        item.mrp_snapshot = item.mrp_snapshot if item.mrp_snapshot is not None else variant.mrp
        item.rate_snapshot = item.rate_snapshot if item.rate_snapshot is not None else variant.selling_price
        item.source_type = item.source_type or "barcode"
    else:
        item = PosCartItem(
            cart_id=cart.id,
            variant_id=variant.id,
            qty=1,
            unit_price=variant.selling_price,
            item_name_snapshot=variant.family.family_name if variant.family else variant.item_display_name,
            barcode_snapshot=variant.barcode,
            tally_stock_item_name_snapshot=variant.family.tally_stock_item_name if variant.family else None,
            mrp_snapshot=variant.mrp,
            rate_snapshot=variant.selling_price,
            source_type="barcode",
            is_manual_line=False,
        )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "ok": True,
        "status": "updated" if is_update else "added",
        "message": "Quantity updated." if is_update else "Added to cart.",
        "barcode": barcode,
        "item": _cart_item_payload(item),
        "cart": _cart_payload(db, cart),
    }


@router.post("/pos/lookup-barcodes")
async def pos_lookup_barcodes(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    seen: set[str] = set()
    candidates: list[str] = []
    for raw_candidate in payload.get("candidates", []):
        candidate = normalize_barcode(str(raw_candidate))
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)
        if len(candidates) >= 12:
            break

    matches = []
    for candidate in candidates:
        variant = lookup_saved_price_by_barcode(db, candidate)
        if variant:
            matches.append(
                {
                    "barcode": variant.barcode,
                    "item_name": variant.item_display_name,
                    "selling_price": _money(variant.selling_price),
                    "missing_price": variant.selling_price is None,
                }
            )
    return {"ok": True, "matches": matches}


@router.post("/pos/cart/tally-items/{tally_item_id}/add")
def add_tally_item_to_cart(tally_item_id: int, db: Session = Depends(get_db)):
    tally_item = db.get(TallyItem, tally_item_id)
    if not tally_item or tally_item.active_status != "active":
        return _json_error("Tally item was not found.", status_code=404, status="not_found")

    item_name = tally_item.name
    cart = _active_cart(db)
    item = PosCartItem(
        cart_id=cart.id,
        variant_id=None,
        qty=1,
        source_type="tally_item",
        item_name_snapshot=item_name,
        tally_stock_item_name_snapshot=item_name,
        is_manual_line=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "ok": True,
        "status": "added",
        "message": "Added to cart.",
        "item": _cart_item_payload(item),
        "cart": _cart_payload(db, cart),
    }



@router.post("/pos/cart/manual/add")
async def add_manual_item_to_cart(request: Request, db: Session = Depends(get_db)):
    return _json_error("Manual POS lines are deprecated. Scan a barcode or search a Tally item.", status_code=410, status="gone")

@router.post("/pos/cart/items/{item_id}/update")
async def update_pos_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _active_cart_item_or_error(db, item_id)
    if isinstance(item, JSONResponse):
        return item
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if "qty" in payload:
        try:
            qty = int(str(payload.get("qty", "")).strip())
        except ValueError:
            return _json_error("Quantity must be a non-zero number.", status_code=400, status="invalid_qty")
        if qty == 0:
            return _json_error("Quantity cannot be zero.", status_code=400, status="invalid_qty")
        item.qty = qty

    if "item_name" in payload:
        return _json_error("Use item replacement to change the product.", status_code=400, status="invalid_item_name")

    if "mrp" in payload:
        try:
            mrp = _decimal_or_none(payload.get("mrp"))
        except ValueError as exc:
            return _json_error(str(exc), status_code=400, status="invalid_mrp")
        if mrp is not None and mrp < 0:
            return _json_error("MRP cannot be negative.", status_code=400, status="invalid_mrp")
        item.mrp_snapshot = mrp

    if "rate" in payload:
        try:
            rate = _decimal_or_none(payload.get("rate"))
        except ValueError as exc:
            return _json_error(str(exc), status_code=400, status="invalid_rate")
        if rate is not None and rate < 0:
            return _json_error("Rate cannot be negative.", status_code=400, status="invalid_rate")
        item.rate_snapshot = rate
        item.unit_price = rate

    if item.mrp_snapshot is not None and item.rate_snapshot is not None:
        if item.mrp_snapshot < item.rate_snapshot:
            return _json_error("MRP cannot be lower than Rate.", status_code=400, status="invalid_mrp")

    db.add(item)
    db.commit()
    return _cart_payload(db, item.cart)


def _duplicate_variant_item(
    db: Session,
    *,
    cart_id: int,
    variant_id: int,
    exclude_item_id: int,
    qty_sign: int,
) -> PosCartItem | None:
    q = (
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart_id)
        .where(PosCartItem.id != exclude_item_id)
        .where(PosCartItem.variant_id == variant_id)
    )
    if qty_sign > 0:
        q = q.where(PosCartItem.qty > 0)
    else:
        q = q.where(PosCartItem.qty < 0)
    return db.scalar(q.order_by(PosCartItem.id))


def _duplicate_tally_item(
    db: Session,
    *,
    cart_id: int,
    tally_name: str,
    exclude_item_id: int,
    qty_sign: int,
) -> PosCartItem | None:
    q = (
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart_id)
        .where(PosCartItem.id != exclude_item_id)
        .where(PosCartItem.variant_id.is_(None))
        .where(PosCartItem.source_type == "tally_item")
        .where(PosCartItem.tally_stock_item_name_snapshot == tally_name)
    )
    if qty_sign > 0:
        q = q.where(PosCartItem.qty > 0)
    else:
        q = q.where(PosCartItem.qty < 0)
    return db.scalar(q.order_by(PosCartItem.id))


def _merge_replaced_item(db: Session, *, target: PosCartItem, duplicate: PosCartItem, replacement_rate: Decimal | None = None) -> PosCartItem:
    if (duplicate.qty > 0 and target.qty < 0) or (duplicate.qty < 0 and target.qty > 0):
        return target
        
    merged_qty = (duplicate.qty or 1) + (target.qty or 1)
    if merged_qty == 0:
        return target

    duplicate.qty = merged_qty
    rate = duplicate.rate_snapshot if duplicate.rate_snapshot is not None else duplicate.unit_price
    target_rate = target.rate_snapshot if target.rate_snapshot is not None else target.unit_price
    
    if rate is None or rate <= 0:
        if replacement_rate is not None and replacement_rate > 0:
            duplicate.rate_snapshot = replacement_rate
            duplicate.unit_price = replacement_rate
        elif target_rate is not None and target_rate > 0:
            duplicate.rate_snapshot = target_rate
            duplicate.unit_price = target_rate
            
    db.add(duplicate)
    db.delete(target)
    return duplicate


@router.post("/pos/cart/items/{item_id}/replace")
async def replace_pos_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = _active_cart_item_or_error(db, item_id)
    if isinstance(item, JSONResponse):
        return item
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    result_type = str(payload.get("result_type", "")).strip()
    result_id = payload.get("id")
    merged_item: PosCartItem | None = None
    if result_type == "barcode":
        variant = db.get(LabelVariant, result_id)
        if not variant or variant.status != "active":
            return _json_error("Barcode item was not found.", status_code=404, status="not_found")
        if item.variant_id == variant.id:
            pass
        else:
            qty_sign = 1 if (item.qty or 1) > 0 else -1
            duplicate = _duplicate_variant_item(db, cart_id=item.cart_id, variant_id=variant.id, exclude_item_id=item.id, qty_sign=qty_sign)
            if duplicate:
                merged_item = _merge_replaced_item(db, target=item, duplicate=duplicate, replacement_rate=variant.selling_price)
            else:
                _apply_variant_to_cart_item(item, variant, preserve_values=True)
    elif result_type == "tally_item":
        tally_item = db.get(TallyItem, result_id)
        if not tally_item or not tally_item.active_status:
            return _json_error("Tally item was not found.", status_code=404, status="not_found")
        tally_name = tally_item.name or "Tally item"
        if item.source_type == "tally_item" and item.tally_stock_item_name_snapshot == tally_name:
            pass
        else:
            _apply_tally_item_to_cart_item(item, tally_item, preserve_values=True)
    elif result_type == "family":
        family = db.get(ProductFamily, result_id)
        if not family or not family.active_status:
            return _json_error("Product family was not found.", status_code=404, status="not_found")
        _apply_family_to_cart_item(item, family, preserve_values=True)
    else:
        return _json_error("Choose a valid item to replace this line.", status_code=400, status="invalid_item")

    if merged_item:
        db.add(merged_item)
    else:
        db.add(item)
    db.commit()
    if merged_item:
        db.refresh(merged_item)
        payload = _cart_payload(db, merged_item.cart)
        payload["merged_item_id"] = merged_item.id
        payload["item"] = _cart_item_payload(merged_item)
        payload["status"] = "merged"
        payload["message"] = "Merged with existing line."
        return payload
    db.refresh(item)
    payload = _cart_payload(db, item.cart)
    payload["item"] = _cart_item_payload(item)
    return payload


@router.post("/pos/cart/items/{item_id}/increase")
def increase_pos_item(item_id: int, db: Session = Depends(get_db)):
    item = _active_cart_item_or_error(db, item_id)
    if isinstance(item, JSONResponse):
        return item
    cart = item.cart
    item.qty += 1
    db.add(item)
    db.commit()
    return _cart_payload(db, cart)


@router.post("/pos/cart/items/{item_id}/decrease")
def decrease_pos_item(item_id: int, db: Session = Depends(get_db)):
    item = _active_cart_item_or_error(db, item_id)
    if isinstance(item, JSONResponse):
        return item
    cart = item.cart
    item.qty = max(1, item.qty - 1)
    db.add(item)
    db.commit()
    return _cart_payload(db, cart)


@router.post("/pos/cart/items/{item_id}/remove")
def remove_pos_item(item_id: int, db: Session = Depends(get_db)):
    item = _active_cart_item_or_error(db, item_id)
    if isinstance(item, JSONResponse):
        return item
    cart = item.cart
    db.delete(item)
    db.commit()
    return _cart_payload(db, cart)


@router.post("/pos/cart/clear")
def clear_pos_cart(db: Session = Depends(get_db)):
    cart = _find_active_cart(db, normalize_duplicates=True)
    if not cart:
        return _empty_cart_payload()
    if cart.cart_mode in (SALE_COPY_CART_MODE, "sale_edit") or cart.source_sale_id is not None:
        cart.cart_mode = NORMAL_CART_MODE
        cart.source_sale_id = None
        db.add(cart)
    items = db.execute(
        select(PosCartItem).where(PosCartItem.cart_id == cart.id)
    ).scalars().all()
    for item in items:
        db.delete(item)
    db.commit()
    return _cart_payload(db, cart)



