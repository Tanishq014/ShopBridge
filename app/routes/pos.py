from __future__ import annotations

import logging
import time
from io import BytesIO
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import LabelVariant, PosCart, PosCartItem, ProductFamily, Sale
from app.services.barcode_service import normalize_barcode
from app.services.billing_service import lookup_saved_price_by_barcode
from app.services.network_service import phone_print_url, qr_url_for_phone_print, qr_url_for_scanner, scanner_url
from app.services.sales_service import CheckoutError, checkout_cart
from app.services.template_filters import register_template_filters


router = APIRouter(tags=["pos"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))
logger = logging.getLogger(__name__)
_pos_cart_heartbeat: dict[str, object] = {
    "signature": None,
    "last_log_at": 0.0,
}


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


def _find_active_cart(db: Session) -> PosCart | None:
    return db.scalar(
        select(PosCart)
        .where(PosCart.status == "active")
        .order_by(PosCart.id.desc())
    )


def _active_cart(db: Session) -> PosCart:
    cart = _find_active_cart(db)
    if cart:
        return cart
    cart = PosCart(status="active")
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


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
    source_type = item.source_type or ("barcode" if variant else "manual")
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
        "status": "active",
        "items": [],
        "total": "0.00",
        "count": 0,
    }


def _cart_payload(db: Session, cart: PosCart | None = None) -> dict[str, object]:
    cart = cart or _find_active_cart(db)
    if not cart:
        return _empty_cart_payload()
    items = db.execute(
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart.id)
        .order_by(PosCartItem.id)
    ).scalars().all()
    total = Decimal("0")
    rows = []
    for item in items:
        rows.append(_cart_item_payload(item))
        rate = _line_rate(item)
        if rate is not None:
            total += rate * item.qty
    return {
        "cart_id": cart.id,
        "status": cart.status,
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
        "family_name": family.family_name if family else "",
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
        "result_type": "tally_item",
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
    recent_sales = db.execute(
        select(Sale)
        .options(selectinload(Sale.items))
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(20)
    ).scalars().all()
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
            "recent_sales": [
                {
                    "id": sale.id,
                    "bill_number": sale.bill_number,
                    "created_at": sale.created_at.isoformat() if sale.created_at else "",
                    "total": _money(sale.total),
                    "items": len(sale.items),
                }
                for sale in recent_sales
            ],
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


@router.post("/pos/cart/load-sale/{sale_id}")
def load_sale_into_pos_cart(sale_id: int, db: Session = Depends(get_db)):
    sale = db.scalar(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(Sale.id == sale_id)
    )
    if not sale:
        return _json_error("Saved bill was not found.", status_code=404, status="not_found")

    cart = _active_cart(db)
    current_items = db.execute(
        select(PosCartItem).where(PosCartItem.cart_id == cart.id)
    ).scalars().all()
    for item in current_items:
        db.delete(item)

    for sale_item in sale.items:
        rate = sale_item.rate
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
            source_type="barcode" if sale_item.label_variant_id else "tally_item",
            is_manual_line=False,
        )
        db.add(cart_item)

    db.commit()
    return {
        "ok": True,
        "status": "loaded",
        "message": "Saved bill loaded into POS.",
        "source_sale_id": sale.id,
        "bill_number": sale.bill_number,
        "cart": _cart_payload(db, cart),
    }


@router.get("/pos/search")
def pos_search(q: str = Query("", max_length=120), db: Session = Depends(get_db)):
    term = (q or "").strip()
    if not term:
        return {"ok": True, "items": []}

    lowered = term.lower()
    like = f"%{lowered}%"
    clean_barcode = normalize_barcode(term)
    variants = db.execute(
        select(LabelVariant)
        .outerjoin(LabelVariant.family)
        .options(joinedload(LabelVariant.family))
        .where(LabelVariant.status == "active")
        .where(
            or_(
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
    families = db.execute(
        select(ProductFamily)
        .where(ProductFamily.active_status.is_(True))
        .where(
            or_(
                func.lower(ProductFamily.family_name).like(like),
                func.lower(ProductFamily.tally_stock_item_name).like(like),
            )
        )
        .order_by(ProductFamily.updated_at.desc(), ProductFamily.id.desc())
        .limit(40)
    ).scalars().all()

    def rank(variant: LabelVariant) -> tuple[int, str]:
        exact_barcode = clean_barcode and variant.barcode == clean_barcode
        starts = any(
            (value or "").lower().startswith(lowered)
            for value in (
                variant.item_display_name,
                variant.article_no,
                variant.brand,
                variant.family.family_name if variant.family else "",
            )
        )
        return (0 if exact_barcode else 1 if starts else 2, variant.item_display_name.lower())

    variants.sort(key=rank)
    variant_family_ids = {variant.family_id for variant in variants if variant.family_id}

    def family_rank(family: ProductFamily) -> tuple[int, str]:
        starts = any(
            (value or "").lower().startswith(lowered)
            for value in (family.family_name, family.tally_stock_item_name)
        )
        return (1 if starts else 3, (family.family_name or family.tally_stock_item_name or "").lower())

    families.sort(key=family_rank)
    family_results = []
    for family in families:
        if len(family_results) >= 12:
            break
        if family.id in variant_family_ids and not family.tally_stock_item_name:
            continue
        family_results.append(_family_search_payload(family))

    results = family_results[:12]
    if len(results) < 12:
        for variant in variants[:12]:
            if len(results) >= 12:
                break
            results.append(
                _variant_search_payload(variant, exact_barcode=bool(clean_barcode and variant.barcode == clean_barcode))
            )
    return {
        "ok": True,
        "items": results,
    }


@router.post("/pos/checkout")
def pos_checkout(
    payment_mode: str = Form("cash"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    cart = _find_active_cart(db)
    if not cart:
        latest_sale = db.scalar(select(Sale).order_by(Sale.id.desc()))
        if latest_sale:
            return RedirectResponse(f"/sales/{latest_sale.id}", status_code=303)
        return RedirectResponse(f"/pos?{urlencode({'checkout_error': 'No active cart to checkout.'})}", status_code=303)
    try:
        sale = checkout_cart(db, cart, payment_mode=payment_mode, notes=notes)
    except CheckoutError as exc:
        return RedirectResponse(f"/pos?{urlencode({'checkout_error': str(exc)})}", status_code=303)
    return RedirectResponse(f"/sales/{sale.id}", status_code=303)


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
    item = db.scalar(
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart.id)
        .where(PosCartItem.variant_id == variant.id)
    )
    if item:
        item.qty += 1
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
        "status": "added",
        "message": "Added to cart.",
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


@router.post("/pos/cart/tally-items/{family_id}/add")
def add_tally_item_to_cart(family_id: int, db: Session = Depends(get_db)):
    family = db.get(ProductFamily, family_id)
    if not family or not family.active_status:
        return _json_error("Tally item was not found.", status_code=404, status="not_found")

    item_name = family.family_name or family.tally_stock_item_name or "Tally item"
    tally_name = family.tally_stock_item_name or item_name
    cart = _active_cart(db)
    item = db.scalar(
        select(PosCartItem)
        .where(PosCartItem.cart_id == cart.id)
        .where(PosCartItem.variant_id.is_(None))
        .where(PosCartItem.source_type == "tally_item")
        .where(PosCartItem.tally_stock_item_name_snapshot == tally_name)
    )
    if item:
        item.qty += 1
    else:
        item = PosCartItem(
            cart_id=cart.id,
            variant_id=None,
            qty=1,
            unit_price=None,
            item_name_snapshot=item_name,
            barcode_snapshot="",
            tally_stock_item_name_snapshot=tally_name,
            mrp_snapshot=None,
            rate_snapshot=None,
            source_type="tally_item",
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


@router.post("/pos/cart/items/{item_id}/update")
async def update_pos_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(PosCartItem, item_id)
    if not item or not item.cart or item.cart.status != "active":
        return _json_error("Cart item was not found.", status_code=404, status="not_found")
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    if "qty" in payload:
        try:
            qty = int(str(payload.get("qty", "")).strip())
        except ValueError:
            return _json_error("Quantity must be a positive number.", status_code=400, status="invalid_qty")
        if qty <= 0:
            return _json_error("Quantity must be at least 1.", status_code=400, status="invalid_qty")
        item.qty = qty

    if "item_name" in payload:
        item_name = str(payload.get("item_name", "")).strip()
        if not item_name:
          return _json_error("Item name cannot be empty.", status_code=400, status="invalid_item_name")
        item.item_name_snapshot = item_name

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

    db.add(item)
    db.commit()
    return _cart_payload(db, item.cart)


@router.post("/pos/cart/items/{item_id}/increase")
def increase_pos_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(PosCartItem, item_id)
    if not item:
        return _json_error("Cart item was not found.", status_code=404, status="not_found")
    cart = item.cart
    item.qty += 1
    db.add(item)
    db.commit()
    return _cart_payload(db, cart)


@router.post("/pos/cart/items/{item_id}/decrease")
def decrease_pos_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(PosCartItem, item_id)
    if not item:
        return _json_error("Cart item was not found.", status_code=404, status="not_found")
    cart = item.cart
    item.qty = max(1, item.qty - 1)
    db.add(item)
    db.commit()
    return _cart_payload(db, cart)


@router.post("/pos/cart/items/{item_id}/remove")
def remove_pos_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(PosCartItem, item_id)
    if not item:
        return _json_error("Cart item was not found.", status_code=404, status="not_found")
    cart = item.cart
    db.delete(item)
    db.commit()
    return _cart_payload(db, cart)


@router.post("/pos/cart/clear")
def clear_pos_cart(db: Session = Depends(get_db)):
    cart = _find_active_cart(db)
    if not cart:
        return _empty_cart_payload()
    items = db.execute(
        select(PosCartItem).where(PosCartItem.cart_id == cart.id)
    ).scalars().all()
    for item in items:
        db.delete(item)
    db.commit()
    return _cart_payload(db, cart)
