import csv
import io
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import TallyItem

from app.config import DEFAULT_TALLY_DSN, TEMPLATES_DIR
from app.db import get_db
from app.services.template_filters import register_template_filters
from app.services.tally_odbc_service import (
    import_tally_items,
    is_pyodbc_available,
    list_odbc_dsns,
    test_dsn,
)


router = APIRouter(prefix="/tally", tags=["tally"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))


@router.get("/", response_class=HTMLResponse)
def tally_home(request: Request):
    return templates.TemplateResponse(
        request,
        "tally.html",
        {
            "request": request,
            "default_dsn": DEFAULT_TALLY_DSN,
            "dsns": list_odbc_dsns(),
            "pyodbc_available": is_pyodbc_available(),
            "result": None,
            "import_result": None,
            "error": None,
        },
    )


@router.post("/test", response_class=HTMLResponse)
def tally_test(request: Request, dsn: str = Form(DEFAULT_TALLY_DSN)):
    result = test_dsn(dsn.strip() or DEFAULT_TALLY_DSN)
    return templates.TemplateResponse(
        request,
        "tally.html",
        {
            "request": request,
            "default_dsn": dsn,
            "dsns": list_odbc_dsns(),
            "pyodbc_available": is_pyodbc_available(),
            "result": result,
            "import_result": None,
            "error": None,
        },
    )


@router.post("/import-stock-items", response_class=HTMLResponse)
def tally_import(
    request: Request,
    dsn: str = Form(DEFAULT_TALLY_DSN),
    db: Session = Depends(get_db),
):
    error = None
    import_result = None
    try:
        import_result = import_tally_items(db, dsn.strip() or DEFAULT_TALLY_DSN)
    except Exception as exc:
        error = str(exc)

    return templates.TemplateResponse(
        request,
        "tally.html",
        {
            "request": request,
            "default_dsn": dsn,
            "dsns": list_odbc_dsns(),
            "pyodbc_available": is_pyodbc_available(),
            "result": None,
            "import_result": import_result,
            "error": error,
        },
    )

@router.post("/import-csv", response_class=HTMLResponse)
async def tally_import_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    error = None
    csv_result = None
    try:
        content = await file.read()
        text_content = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text_content))
        
        created = 0
        updated = 0
        total = 0
        
        for row in reader:
            total += 1
            item_name = row.get("Item Name", "").strip()
            aliases = row.get("Aliases", "").strip()
            
            if not item_name:
                continue
                
            normalized = item_name.lower()
            existing = db.scalar(select(TallyItem).where(TallyItem.normalized_name == normalized))
            
            if existing:
                if existing.aliases != aliases:
                    existing.aliases = aliases
                    updated += 1
            else:
                db.add(TallyItem(
                    name=item_name,
                    normalized_name=normalized,
                    aliases=aliases,
                    active_status="active",
                    source="csv"
                ))
                created += 1
                
        db.commit()
        csv_result = {"total": total, "created": created, "updated": updated}
        
    except Exception as exc:
        error = str(exc)

    return templates.TemplateResponse(
        request,
        "tally.html",
        {
            "request": request,
            "default_dsn": DEFAULT_TALLY_DSN,
            "dsns": list_odbc_dsns(),
            "pyodbc_available": is_pyodbc_available(),
            "result": None,
            "import_result": None,
            "csv_result": csv_result,
            "error": error,
        },
    )
