from __future__ import annotations

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
