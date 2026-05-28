from __future__ import annotations

from pathlib import Path

from app.config import PREVIEWS_DIR
from app.models import TemplateMaster
from app.services.bartender_activex_service import export_print_preview_to_image
from app.services.field_config import parse_field_defaults


TEMPLATE_PREVIEWS_DIR = PREVIEWS_DIR / "templates"


def cached_template_preview_path(template: TemplateMaster) -> Path:
    return TEMPLATE_PREVIEWS_DIR / f"template_{template.id}.jpg"


def clear_cached_template_preview(template: TemplateMaster) -> None:
    path = cached_template_preview_path(template)
    if path.exists():
        path.unlink()


def cached_template_preview_url(template: TemplateMaster) -> str:
    path = cached_template_preview_path(template)
    if not path.is_file():
        return ""
    return f"/new-stock/template-preview/{template.id}?v={path.stat().st_mtime_ns}"


def refresh_cached_template_preview(template: TemplateMaster, *, visible: bool = False) -> Path:
    if template.id is None:
        raise ValueError("Template must be saved before caching a preview.")

    TEMPLATE_PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    clear_cached_template_preview(template)

    default_values = parse_field_defaults(template.default_field_values)
    generated_path = export_print_preview_to_image(
        template.bartender_file_path,
        default_values,
        TEMPLATE_PREVIEWS_DIR,
        visible=visible,
    )
    final_path = cached_template_preview_path(template)
    generated_prefix = generated_path.stem.rsplit("_", 1)[0]
    generated_siblings = list(generated_path.parent.glob(f"{generated_prefix}_*{generated_path.suffix}"))
    if generated_path != final_path:
        generated_path.replace(final_path)
    for sibling in generated_siblings:
        if sibling != final_path and sibling.exists():
            sibling.unlink()
    return final_path
