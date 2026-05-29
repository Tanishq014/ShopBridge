from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import PosCart, PosCartItem
from app.services.barcode_service import normalize_barcode
from app.services.billing_service import lookup_saved_price_by_barcode


router = APIRouter(tags=["pos"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


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
    category = variant.family.category if variant and variant.family else ""
    template_name = variant.template.template_name if variant and variant.template else ""
    amount = item.unit_price * item.qty if item.unit_price is not None else None
    return {
        "id": item.id,
        "variant_id": item.variant_id,
        "barcode": variant.barcode,
        "item_name": variant.item_display_name,
        "category": category or "",
        "template_name": template_name or "",
        "mrp": _money(variant.mrp),
        "selling_price": _money(item.unit_price),
        "coded_price": variant.coded_price or "",
        "qty": item.qty,
        "amount": _money(amount),
        "missing_price": item.unit_price is None,
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
        if item.unit_price is not None:
            total += item.unit_price * item.qty
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


@router.get("/pos", response_class=HTMLResponse)
def pos_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "pos.html",
        {"request": request},
    )


@router.get("/scanner", response_class=HTMLResponse)
def scanner_page(request: Request):
    return templates.TemplateResponse(
        request,
        "scanner.html",
        {"request": request},
    )


@router.get("/pos/cart")
def pos_cart(db: Session = Depends(get_db)):
    return _cart_payload(db)


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
            item_name=variant.item_display_name,
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
    else:
        item = PosCartItem(
            cart_id=cart.id,
            variant_id=variant.id,
            qty=1,
            unit_price=variant.selling_price,
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
