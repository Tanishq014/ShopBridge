from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import (
    BARTENDER_TEMPLATES_DIR,
    DATA_DIR,
    DATABASE_URL,
    EXPORTS_DIR,
    PRINT_JOBS_DIR,
)


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def ensure_directories() -> None:
    for directory in (DATA_DIR, PRINT_JOBS_DIR, EXPORTS_DIR, BARTENDER_TEMPLATES_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    ensure_directories()
    from app.models import TemplateMaster
    from app.services.field_config import default_required_fields_csv

    Base.metadata.create_all(bind=engine)
    _migrate_existing_sqlite()
    with SessionLocal() as db:
        existing = db.scalar(
            select(TemplateMaster).where(TemplateMaster.template_id == "DEFAULT")
        )
        if existing:
            return

        db.add(
            TemplateMaster(
                template_id="DEFAULT",
                template_name="Default Sticker",
                label_size="50 x 25 mm",
                has_logo=False,
                category="General",
                bartender_file_path=str(BARTENDER_TEMPLATES_DIR / "default.btw"),
                printer_name="",
                required_fields=default_required_fields_csv(),
                active_status=True,
            )
        )
        db.commit()


def _migrate_existing_sqlite() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "label_variants" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("label_variants")}
    if "expiry" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE label_variants ADD COLUMN expiry VARCHAR(120)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
