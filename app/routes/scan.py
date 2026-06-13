from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from app.services.barcode_service import normalize_barcode

router = APIRouter(tags=["scan"])

@router.get("/scan")
def scan_redirect(
    barcode: str = "",
):
    clean_barcode = normalize_barcode(barcode)
    url = "/variants/"
    if clean_barcode:
        url += f"?{urlencode({'search': clean_barcode})}"
    return RedirectResponse(url, status_code=303)
