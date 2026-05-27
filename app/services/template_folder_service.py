from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BARTENDER_TEMPLATES_DIR
from app.models import TemplateMaster


KNOWN_TEMPLATE_CATEGORIES = {"clothes", "cosmetics", "gifts", "toys"}


@dataclass(frozen=True)
class TemplateFolderScanResult:
    found: int
    imported: int
    skipped: int
    deactivated_placeholders: int


def template_id_from_path(path: Path) -> str:
    template_id = re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_").upper()
    return template_id or "TEMPLATE"


def unique_template_id(db: Session, base_template_id: str) -> str:
    template_id = base_template_id
    counter = 2
    while db.scalar(select(TemplateMaster).where(TemplateMaster.template_id == template_id)):
        template_id = f"{base_template_id}_{counter}"
        counter += 1
    return template_id


def normalized_path(value: str | Path) -> str:
    return str(Path(value)).lower()


def bartender_template_files() -> list[Path]:
    BARTENDER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(BARTENDER_TEMPLATES_DIR.rglob("*.btw"))


def folder_template_options() -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for path in bartender_template_files():
        resolved = path.resolve()
        try:
            display = str(path.relative_to(BARTENDER_TEMPLATES_DIR))
        except ValueError:
            display = path.name
        options.append({"path": str(resolved), "display": display})
    return options


def template_path_exists(template: TemplateMaster) -> bool:
    if not template.bartender_file_path:
        return False
    return Path(template.bartender_file_path).expanduser().is_file()


def _category_from_path(path: Path) -> str | None:
    try:
        relative = path.relative_to(BARTENDER_TEMPLATES_DIR)
    except ValueError:
        return None

    if len(relative.parts) < 2:
        return None

    folder = relative.parts[0].strip().lower()
    return folder if folder in KNOWN_TEMPLATE_CATEGORIES else None


def _deactivate_missing_default(db: Session) -> int:
    default_template = db.scalar(
        select(TemplateMaster).where(TemplateMaster.template_id == "DEFAULT")
    )
    if not default_template or template_path_exists(default_template):
        return 0

    if default_template.active_status is False and not default_template.required_fields:
        return 0

    default_template.active_status = False
    default_template.required_fields = None
    db.add(default_template)
    return 1


def scan_bartender_template_folder(db: Session) -> TemplateFolderScanResult:
    template_files = bartender_template_files()
    existing_paths = {
        normalized_path(path)
        for path in db.execute(select(TemplateMaster.bartender_file_path)).scalars().all()
        if path
    }

    imported = 0
    skipped = 0

    for path in template_files:
        full_path = str(path.resolve())
        if normalized_path(full_path) in existing_paths:
            skipped += 1
            continue

        template_id = unique_template_id(db, template_id_from_path(path))
        db.add(
            TemplateMaster(
                template_id=template_id,
                template_name=path.stem.replace("_", " ").replace("-", " ").title(),
                label_size=None,
                has_logo=False,
                category=_category_from_path(path),
                bartender_file_path=full_path,
                printer_name=None,
                required_fields=None,
                active_status=True,
            )
        )
        existing_paths.add(normalized_path(full_path))
        imported += 1

    if imported:
        db.flush()

    deactivated_placeholders = _deactivate_missing_default(db)
    db.commit()

    return TemplateFolderScanResult(
        found=len(template_files),
        imported=imported,
        skipped=skipped,
        deactivated_placeholders=deactivated_placeholders,
    )
