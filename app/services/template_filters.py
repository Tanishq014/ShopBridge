from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.services.time_service import format_local_datetime


def register_template_filters(templates: Jinja2Templates) -> Jinja2Templates:
    templates.env.filters["local_time"] = format_local_datetime
    return templates
