from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import PrintJob
from app.services.barcode_service import normalize_barcode
from app.services.billing_service import lookup_saved_price_by_barcode


router = APIRouter(tags=["scan"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/scan", response_class=HTMLResponse)
def scan_lookup(
    request: Request,
    barcode: str = "",
    db: Session = Depends(get_db),
):
    clean_barcode = normalize_barcode(barcode)
    variant = lookup_saved_price_by_barcode(db, clean_barcode) if clean_barcode else None
    jobs = []
    if variant:
        jobs = db.execute(
            select(PrintJob)
            .where(PrintJob.variant_id == variant.id)
            .order_by(PrintJob.created_at.desc(), PrintJob.id.desc())
        ).scalars().all()

    create_query = urlencode({"barcode": clean_barcode}) if clean_barcode else ""
    return templates.TemplateResponse(
        request,
        "scan.html",
        {
            "request": request,
            "barcode": clean_barcode,
            "variant": variant,
            "jobs": jobs,
            "create_url": f"/new-stock?{create_query}" if create_query else "/new-stock",
            "category": variant.family.category if variant and variant.family else "clothes",
            "template_id": variant.template_id if variant else "",
        },
    )
