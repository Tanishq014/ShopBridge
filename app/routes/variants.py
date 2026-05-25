from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import LabelVariant, ProductFamily, TemplateMaster
from app.services.barcode_service import assign_barcode
from app.services.price_code_service import generate_coded_price


router = APIRouter(prefix="/variants", tags=["variants"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int_or_none(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _form_choices(db: Session):
    families = db.execute(
        select(ProductFamily)
        .where(ProductFamily.active_status == True)  # noqa: E712
        .order_by(ProductFamily.family_name)
    ).scalars().all()
    template_choices = db.execute(
        select(TemplateMaster)
        .where(TemplateMaster.active_status == True)  # noqa: E712
        .order_by(TemplateMaster.template_name)
    ).scalars().all()
    return families, template_choices


@router.get("/", response_class=HTMLResponse)
def list_variants(request: Request, db: Session = Depends(get_db)):
    variants = db.execute(
        select(LabelVariant).order_by(LabelVariant.updated_at.desc(), LabelVariant.id.desc())
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "variants.html",
        {
            "request": request,
            "variants": variants,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_variant(request: Request, db: Session = Depends(get_db)):
    families, template_choices = _form_choices(db)
    return templates.TemplateResponse(
        request,
        "variant_form.html",
        {
            "request": request,
            "variant": None,
            "families": families,
            "template_choices": template_choices,
            "error": None,
        },
    )


@router.post("/")
def create_variant(
    request: Request,
    barcode: str = Form(""),
    family_id: int = Form(...),
    brand: str = Form(""),
    item_display_name: str = Form(...),
    article_no: str = Form(""),
    size: str = Form(""),
    color: str = Form(""),
    batch_no: str = Form(""),
    season: str = Form(""),
    mrp: str = Form(""),
    selling_price: str = Form(""),
    coded_price: str = Form(""),
    template_id: str = Form(""),
    status: str = Form("active"),
    db: Session = Depends(get_db),
):
    families, template_choices = _form_choices(db)
    selling = _decimal_or_none(selling_price)
    coded = coded_price.strip() or generate_coded_price(selling)
    try:
        final_barcode = assign_barcode(db, barcode)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "variant_form.html",
            {
                "request": request,
                "variant": None,
                "families": families,
                "template_choices": template_choices,
                "error": str(exc),
            },
            status_code=400,
        )

    variant = LabelVariant(
        barcode=final_barcode,
        family_id=family_id,
        brand=brand.strip() or None,
        item_display_name=item_display_name.strip(),
        article_no=article_no.strip() or None,
        size=size.strip() or None,
        color=color.strip() or None,
        batch_no=batch_no.strip() or None,
        season=season.strip() or None,
        mrp=_decimal_or_none(mrp),
        selling_price=selling,
        coded_price=coded or None,
        template_id=_int_or_none(template_id),
        status=status,
    )
    db.add(variant)
    db.commit()
    return RedirectResponse("/variants", status_code=303)


@router.get("/{variant_id}/edit", response_class=HTMLResponse)
def edit_variant(variant_id: int, request: Request, db: Session = Depends(get_db)):
    variant = db.get(LabelVariant, variant_id)
    families, template_choices = _form_choices(db)
    return templates.TemplateResponse(
        request,
        "variant_form.html",
        {
            "request": request,
            "variant": variant,
            "families": families,
            "template_choices": template_choices,
            "error": None,
        },
    )


@router.post("/{variant_id}")
def update_variant(
    variant_id: int,
    request: Request,
    barcode: str = Form(""),
    family_id: int = Form(...),
    brand: str = Form(""),
    item_display_name: str = Form(...),
    article_no: str = Form(""),
    size: str = Form(""),
    color: str = Form(""),
    batch_no: str = Form(""),
    season: str = Form(""),
    mrp: str = Form(""),
    selling_price: str = Form(""),
    coded_price: str = Form(""),
    template_id: str = Form(""),
    status: str = Form("active"),
    db: Session = Depends(get_db),
):
    variant = db.get(LabelVariant, variant_id)
    if not variant:
        return RedirectResponse("/variants", status_code=303)

    families, template_choices = _form_choices(db)
    selling = _decimal_or_none(selling_price)
    coded = coded_price.strip() or generate_coded_price(selling)
    try:
        final_barcode = assign_barcode(db, barcode, exclude_variant_id=variant_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "variant_form.html",
            {
                "request": request,
                "variant": variant,
                "families": families,
                "template_choices": template_choices,
                "error": str(exc),
            },
            status_code=400,
        )

    variant.barcode = final_barcode
    variant.family_id = family_id
    variant.brand = brand.strip() or None
    variant.item_display_name = item_display_name.strip()
    variant.article_no = article_no.strip() or None
    variant.size = size.strip() or None
    variant.color = color.strip() or None
    variant.batch_no = batch_no.strip() or None
    variant.season = season.strip() or None
    variant.mrp = _decimal_or_none(mrp)
    variant.selling_price = selling
    variant.coded_price = coded or None
    variant.template_id = _int_or_none(template_id)
    variant.status = status
    db.add(variant)
    db.commit()
    return RedirectResponse("/variants", status_code=303)


@router.post("/{variant_id}/deactivate")
def deactivate_variant(variant_id: int, db: Session = Depends(get_db)):
    variant = db.get(LabelVariant, variant_id)
    if variant:
        variant.status = "inactive"
        db.add(variant)
        db.commit()
    return RedirectResponse("/variants", status_code=303)


@router.post("/{variant_id}/activate")
def activate_variant(variant_id: int, db: Session = Depends(get_db)):
    variant = db.get(LabelVariant, variant_id)
    if variant:
        variant.status = "active"
        db.add(variant)
        db.commit()
    return RedirectResponse("/variants", status_code=303)


@router.get("/{variant_id}/preview", response_class=HTMLResponse)
def sticker_preview(variant_id: int, request: Request, db: Session = Depends(get_db)):
    variant = db.get(LabelVariant, variant_id)
    if not variant:
        return RedirectResponse("/variants", status_code=303)
    return templates.TemplateResponse(
        request,
        "sticker_preview.html",
        {
            "request": request,
            "variant": variant,
        },
    )
