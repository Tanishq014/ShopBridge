from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.services.network_service import phone_print_url, qr_url_for_phone_print, qr_url_for_scanner, scanner_url
from app.services.time_service import format_local_datetime


def register_template_filters(templates: Jinja2Templates) -> Jinja2Templates:
    templates.env.filters["local_time"] = format_local_datetime
    templates.env.globals["navbar_qr_context"] = navbar_qr_context
    return templates


def navbar_qr_context(request: Request) -> dict[str, object]:
    headers = getattr(request, "headers", None)
    request_host = headers.get("host") if headers and hasattr(headers, "get") else None
    scanner, _ = scanner_url(request_host)
    phone_print, _ = phone_print_url(request_host)
    return {
        "scanner_url": scanner,
        "scanner_qr_url": qr_url_for_scanner(scanner),
        "phone_print_url": phone_print,
        "phone_print_qr_url": qr_url_for_phone_print(phone_print),
    }
