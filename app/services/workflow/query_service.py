from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LabelVariant, PrintJob, ProductFamily, TemplateMaster


def active_templates(db: Session) -> list[TemplateMaster]:
    return db.execute(
        select(TemplateMaster)
        .where(TemplateMaster.active_status == True)  # noqa: E712
        .order_by(TemplateMaster.category, TemplateMaster.template_name)
    ).scalars().all()


def active_families(db: Session) -> list[ProductFamily]:
    return db.execute(
        select(ProductFamily)
        .where(ProductFamily.active_status == True)  # noqa: E712
        .order_by(ProductFamily.category, ProductFamily.family_name)
    ).scalars().all()


def search_variants(db: Session) -> list[LabelVariant]:
    return db.execute(
        select(LabelVariant)
        .where(LabelVariant.status == "active")
        .order_by(LabelVariant.updated_at.desc(), LabelVariant.id.desc())
    ).scalars().all()


def recent_variants(db: Session, limit: int = 80) -> list[LabelVariant]:
    return search_variants(db)[:limit]


def recent_print_jobs(db: Session, limit: int = 10) -> list[PrintJob]:
    return db.execute(
        select(PrintJob).order_by(PrintJob.created_at.desc(), PrintJob.id.desc()).limit(limit)
    ).scalars().all()


def recent_templates(db: Session, template_rows: list[TemplateMaster], limit: int = 6) -> list[TemplateMaster]:
    seen: set[int] = set()
    recent: list[TemplateMaster] = []
    jobs = recent_print_jobs(db, 40)
    for job in jobs:
        if job.template and job.template.active_status and job.template.id not in seen:
            recent.append(job.template)
            seen.add(job.template.id)
        if len(recent) >= limit:
            return recent

    for template in template_rows:
        if template.id not in seen:
            recent.append(template)
            seen.add(template.id)
        if len(recent) >= limit:
            break
    return recent
