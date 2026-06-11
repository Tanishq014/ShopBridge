from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEFAULT_TALLY_DSN
from app.models import TallyItem


@dataclass
class TallyTestResult:
    pyodbc_available: bool
    dsn: str
    success: bool
    message: str
    table_names: list[str] = field(default_factory=list)


def _pyodbc():
    try:
        import pyodbc  # type: ignore
    except ImportError:
        return None
    return pyodbc


def is_pyodbc_available() -> bool:
    return _pyodbc() is not None


def list_odbc_dsns() -> dict[str, str]:
    pyodbc = _pyodbc()
    if pyodbc is None:
        return {}
    try:
        return dict(pyodbc.dataSources())
    except Exception:
        return {}


def _connect(dsn: str = DEFAULT_TALLY_DSN):
    pyodbc = _pyodbc()
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed. Install requirements.txt first.")
    return pyodbc.connect(f"DSN={dsn};", autocommit=True, timeout=5)


def test_dsn(dsn: str = DEFAULT_TALLY_DSN) -> TallyTestResult:
    pyodbc_available = is_pyodbc_available()
    if not pyodbc_available:
        return TallyTestResult(
            pyodbc_available=False,
            dsn=dsn,
            success=False,
            message="pyodbc is not installed.",
        )

    try:
        with _connect(dsn) as connection:
            cursor = connection.cursor()
            table_names = []
            try:
                for row in cursor.tables():
                    table_name = getattr(row, "table_name", None)
                    if table_name:
                        table_names.append(str(table_name))
            except Exception as exc:
                return TallyTestResult(
                    pyodbc_available=True,
                    dsn=dsn,
                    success=True,
                    message=f"Connected, but table listing failed: {exc}",
                    table_names=[],
                )

            return TallyTestResult(
                pyodbc_available=True,
                dsn=dsn,
                success=True,
                message=f"Connected to {dsn}.",
                table_names=sorted(set(table_names)),
            )
    except Exception as exc:
        return TallyTestResult(
            pyodbc_available=True,
            dsn=dsn,
            success=False,
            message=str(exc),
        )


def fetch_stock_item_names(dsn: str = DEFAULT_TALLY_DSN) -> tuple[list[str], str]:
    candidate_queries = [
        "SELECT $Name FROM StockItem",
        "SELECT Name FROM StockItem",
        "SELECT $Name FROM StockItems",
        "SELECT Name FROM StockItems",
    ]
    errors: list[str] = []

    with _connect(dsn) as connection:
        cursor = connection.cursor()
        for query in candidate_queries:
            try:
                rows = cursor.execute(query).fetchall()
                names = sorted(
                    {
                        str(row[0]).strip()
                        for row in rows
                        if row and row[0] is not None and str(row[0]).strip()
                    }
                )
                if names:
                    return names, query
            except Exception as exc:
                errors.append(f"{query}: {exc}")

    raise RuntimeError("Could not read Tally stock item names. Tried: " + " | ".join(errors))


def import_tally_items(db: Session, dsn: str = DEFAULT_TALLY_DSN) -> dict[str, object]:
    names, query = fetch_stock_item_names(dsn)
    created = 0
    updated = 0
    skipped = 0
    errors = []

    for name in names:
        try:
            normalized = name.strip().lower()
            existing = db.scalar(
                select(TallyItem).where(TallyItem.normalized_name == normalized)
            )
            if existing:
                if existing.name != name:
                    existing.name = name
                    updated += 1
                else:
                    skipped += 1
                continue

            db.add(
                TallyItem(
                    name=name,
                    normalized_name=normalized,
                    active_status="active",
                    source="odbc",
                )
            )
            created += 1
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


