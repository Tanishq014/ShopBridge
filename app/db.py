from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import (
    BARTENDER_TEMPLATES_DIR,
    DATA_DIR,
    DATABASE_URL,
    EXPORTS_DIR,
    PREVIEWS_DIR,
    PRINT_JOBS_DIR,
)


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def ensure_directories() -> None:
    for directory in (DATA_DIR, PRINT_JOBS_DIR, EXPORTS_DIR, PREVIEWS_DIR, BARTENDER_TEMPLATES_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    ensure_directories()
    from app.models import TemplateMaster
    from app.services.template_folder_service import scan_bartender_template_folder

    Base.metadata.create_all(bind=engine)
    _migrate_existing_sqlite()
    with SessionLocal() as db:
        existing = db.scalar(
            select(TemplateMaster).where(TemplateMaster.template_id == "DEFAULT")
        )
        if not existing:
            db.add(
                TemplateMaster(
                    template_id="DEFAULT",
                    template_name="Default Sticker",
                    label_size=None,
                    has_logo=False,
                    category=None,
                    bartender_file_path=str(BARTENDER_TEMPLATES_DIR / "default.btw"),
                    printer_name=None,
                    required_fields=None,
                    active_status=False,
                )
            )
            db.commit()

        scan_bartender_template_folder(db)


def _migrate_existing_sqlite() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "label_variants" in table_names:
        columns = {column["name"] for column in inspector.get_columns("label_variants")}
        if "expiry" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE label_variants ADD COLUMN expiry VARCHAR(120)"))

    if "template_masters" in table_names:
        columns = {column["name"] for column in inspector.get_columns("template_masters")}
        if "default_field_values" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE template_masters ADD COLUMN default_field_values TEXT"))
        if "barcode_sample_value" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE template_masters ADD COLUMN barcode_sample_value VARCHAR(120)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
