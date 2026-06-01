from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import ProductFamily, TemplateMaster
from app.services.template_filters import register_template_filters


router = APIRouter(prefix="/families", tags=["families"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))


def _decimal(value: str | None, default: Decimal = Decimal("0")) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _int_or_none(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


@router.get("/", response_class=HTMLResponse)
def list_families(
    request: Request,
    edit_id: int | None = None,
    db: Session = Depends(get_db),
):
    families = db.execute(
        select(ProductFamily).order_by(ProductFamily.active_status.desc(), ProductFamily.family_name)
    ).scalars().all()
    template_choices = db.execute(
        select(TemplateMaster).order_by(TemplateMaster.template_name)
    ).scalars().all()
    edit_family = db.get(ProductFamily, edit_id) if edit_id else None
    return templates.TemplateResponse(
        request,
        "families.html",
        {
            "request": request,
            "families": families,
            "template_choices": template_choices,
            "family": edit_family,
        },
    )


@router.post("/")
def create_family(
    family_name: str = Form(...),
    tally_stock_item_name: str = Form(""),
    category: str = Form(""),
    default_tax_rate: str = Form("0"),
    default_unit: str = Form("PCS"),
    default_template_id: str = Form(""),
    active_status: bool = Form(False),
    db: Session = Depends(get_db),
):
    family = ProductFamily(
        family_name=family_name.strip(),
        tally_stock_item_name=tally_stock_item_name.strip() or None,
        category=category.strip() or None,
        default_tax_rate=_decimal(default_tax_rate),
        default_unit=(default_unit.strip() or "PCS"),
        default_template_id=_int_or_none(default_template_id),
        active_status=active_status,
    )
    db.add(family)
    db.commit()
    return RedirectResponse("/families", status_code=303)


@router.post("/{family_id}")
def update_family(
    family_id: int,
    family_name: str = Form(...),
    tally_stock_item_name: str = Form(""),
    category: str = Form(""),
    default_tax_rate: str = Form("0"),
    default_unit: str = Form("PCS"),
    default_template_id: str = Form(""),
    active_status: bool = Form(False),
    db: Session = Depends(get_db),
):
    family = db.get(ProductFamily, family_id)
    if not family:
        return RedirectResponse("/families", status_code=303)

    family.family_name = family_name.strip()
    family.tally_stock_item_name = tally_stock_item_name.strip() or None
    family.category = category.strip() or None
    family.default_tax_rate = _decimal(default_tax_rate)
    family.default_unit = default_unit.strip() or "PCS"
    family.default_template_id = _int_or_none(default_template_id)
    family.active_status = active_status
    db.add(family)
    db.commit()
    return RedirectResponse("/families", status_code=303)


@router.post("/{family_id}/deactivate")
def deactivate_family(family_id: int, db: Session = Depends(get_db)):
    family = db.get(ProductFamily, family_id)
    if family:
        family.active_status = False
        db.add(family)
        db.commit()
    return RedirectResponse("/families", status_code=303)


@router.post("/{family_id}/activate")
def activate_family(family_id: int, db: Session = Depends(get_db)):
    family = db.get(ProductFamily, family_id)
    if family:
        family.active_status = True
        db.add(family)
        db.commit()
    return RedirectResponse("/families", status_code=303)
