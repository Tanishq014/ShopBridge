from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import STATIC_DIR, TEMPLATES_DIR
from app.db import get_db, init_db
from app.models import LabelVariant, PrintJob, ProductFamily, TemplateMaster
from app.routes import families, print_jobs, tally, templates as template_routes, variants


app = FastAPI(title="ShopBridge", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    stats = {
        "families": db.scalar(select(func.count(ProductFamily.id))) or 0,
        "active_variants": db.scalar(
            select(func.count(LabelVariant.id)).where(LabelVariant.status == "active")
        )
        or 0,
        "templates": db.scalar(select(func.count(TemplateMaster.id))) or 0,
        "pending_jobs": db.scalar(
            select(func.count(PrintJob.id)).where(PrintJob.status == "pending")
        )
        or 0,
    }
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "request": request,
            "stats": stats,
        },
    )


app.include_router(families.router)
app.include_router(variants.router)
app.include_router(template_routes.router)
app.include_router(print_jobs.router)
app.include_router(tally.router)
