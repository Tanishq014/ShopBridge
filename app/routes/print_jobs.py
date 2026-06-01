from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import LabelVariant, PrintJob, TemplateMaster
from app.services.bartender_service import create_csv_print_job
from app.services.field_config import parse_required_fields
from app.services.template_filters import register_template_filters
from app.services.template_folder_service import template_path_exists


router = APIRouter(prefix="/print-jobs", tags=["print-jobs"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))


def _choices(db: Session):
    variants = db.execute(
        select(LabelVariant)
        .where(LabelVariant.status == "active")
        .order_by(LabelVariant.item_display_name, LabelVariant.article_no)
    ).scalars().all()
    template_choices = db.execute(
        select(TemplateMaster)
        .where(TemplateMaster.active_status == True)  # noqa: E712
        .order_by(TemplateMaster.template_name)
    ).scalars().all()
    return variants, template_choices


def _render(
    request: Request,
    db: Session,
    error: str | None = None,
    message: str | None = None,
):
    jobs = db.execute(
        select(PrintJob).order_by(PrintJob.created_at.desc(), PrintJob.id.desc())
    ).scalars().all()
    variants, template_choices = _choices(db)
    return templates.TemplateResponse(
        request,
        "print_jobs.html",
        {
            "request": request,
            "jobs": jobs,
            "variants": variants,
            "template_choices": template_choices,
            "error": error,
            "message": message,
        },
    )


@router.get("/", response_class=HTMLResponse)
def list_print_jobs(request: Request, db: Session = Depends(get_db)):
    return _render(request, db)


@router.post("/", response_class=HTMLResponse)
def create_print_job(
    request: Request,
    variant_id: int = Form(...),
    template_id: str = Form(""),
    copies: int = Form(1),
    db: Session = Depends(get_db),
):
    variant = db.get(LabelVariant, variant_id)
    if not variant:
        return _render(request, db, error="Variant was not found.")

    selected_template_id = int(template_id) if template_id else None
    if selected_template_id is None:
        selected_template_id = variant.template_id or variant.family.default_template_id
    if selected_template_id is None:
        return _render(request, db, error="Choose a template or set a default template.")

    template = db.get(TemplateMaster, selected_template_id)
    if not template or not template.active_status:
        return _render(request, db, error="Selected template is not active.")
    if not template_path_exists(template):
        return _render(request, db, error="Selected template file is missing on this PC.")
    if not parse_required_fields(template.required_fields):
        return _render(request, db, error="Extract fields for the selected template before creating a CSV job.")

    job = PrintJob(
        variant_id=variant.id,
        template_id=template.id,
        copies=max(1, copies),
        status="pending",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        path = create_csv_print_job(db, job)
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        db.add(job)
        db.commit()
        return _render(request, db, error=f"Print job created but CSV generation failed: {exc}")

    return _render(request, db, message=f"CSV print job created: {path}")


@router.post("/{job_id}/mark-printed")
def mark_printed(job_id: int, db: Session = Depends(get_db)):
    job = db.get(PrintJob, job_id)
    if job:
        job.status = "printed"
        job.printed_at = datetime.utcnow()
        db.add(job)
        db.commit()
    return RedirectResponse("/print-jobs", status_code=303)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(PrintJob, job_id)
    if job and job.status != "printed":
        job.status = "cancelled"
        db.add(job)
        db.commit()
    return RedirectResponse("/print-jobs", status_code=303)
