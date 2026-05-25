from sqlalchemy import create_engine, select
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

    Base.metadata.create_all(bind=engine)
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
                required_fields="brand,item_display_name,article_no,size,mrp,coded_price,barcode",
                active_status=True,
            )
        )
        db.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

