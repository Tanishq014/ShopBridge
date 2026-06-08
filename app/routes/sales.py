from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import Sale
from app.services.template_filters import register_template_filters


router = APIRouter(tags=["sales"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))


def _sale_or_404(db: Session, sale_id: int) -> Sale:
    sale = db.scalar(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(Sale.id == sale_id)
    )
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found.")
    return sale


def _money(value: Decimal | int | str | None) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):.2f}"


def _sale_payload(sale: Sale) -> dict[str, object]:
    items = []
    for item in sale.items:
        items.append(
            {
                "id": item.id,
                "label_variant_id": item.label_variant_id,
                "barcode": item.barcode or "",
                "item_name": item.item_name or "",
                "billing_item": item.item_name or "",
                "tally_stock_item_name": item.tally_stock_item_name or "",
                "mrp": _money(item.mrp),
                "selling_price": _money(item.rate),
                "rate": _money(item.rate),
                "qty": item.qty,
                "amount": _money(item.amount),
                "discount_amount": _money(item.discount_amount),
                "source_type": "barcode" if item.label_variant_id else "tally_item",
                "missing_price": False,
            }
        )
    return {
        "id": sale.id,
        "bill_number": sale.bill_number,
        "status": sale.status,
        "subtotal": _money(sale.subtotal),
        "discount_total": _money(sale.discount_total),
        "round_off": _money(sale.round_off),
        "total": _money(sale.total),
        "payment_mode": sale.payment_mode,
        "notes": sale.notes or "",
        "print_status": sale.print_status,
        "tally_sync_status": sale.tally_sync_status,
        "created_at": sale.created_at.isoformat() if sale.created_at else "",
        "items": items,
        "count": sum(item.qty for item in sale.items),
    }


@router.get("/sales", response_class=HTMLResponse)
def list_sales(request: Request, db: Session = Depends(get_db)):
    sales = db.execute(
        select(Sale)
        .options(selectinload(Sale.items))
        .order_by(Sale.created_at.desc(), Sale.id.desc())
        .limit(100)
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "sales.html",
        {
            "request": request,
            "sales": sales,
        },
    )


@router.get("/sales/{sale_id}", response_class=HTMLResponse)
def sale_detail(sale_id: int, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "sale_detail.html",
        {
            "request": request,
            "sale": _sale_or_404(db, sale_id),
        },
    )


@router.get("/sales/{sale_id}/receipt", response_class=HTMLResponse)
def sale_receipt(sale_id: int, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "sale_receipt.html",
        {
            "request": request,
            "sale": _sale_or_404(db, sale_id),
        },
    )


@router.get("/sales/{sale_id}/data")
def sale_data(sale_id: int, db: Session = Depends(get_db)):
    sale = _sale_or_404(db, sale_id)
    return {"ok": True, "sale": _sale_payload(sale)}
