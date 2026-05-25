from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import DEFAULT_TALLY_DSN, TEMPLATES_DIR
from app.db import get_db
from app.services.tally_odbc_service import (
    import_stock_items_as_families,
    is_pyodbc_available,
    list_odbc_dsns,
    test_dsn,
)


router = APIRouter(prefix="/tally", tags=["tally"])
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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
        import_result = import_stock_items_as_families(db, dsn.strip() or DEFAULT_TALLY_DSN)
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
