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
    from app.models import ProductFamily, TemplateMaster, TallyItem
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

        _seed_demo_tally_items(db, TallyItem)
        scan_bartender_template_folder(db)


def _migrate_existing_sqlite() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return

    from app.models import PosCartItem, Sale, SaleItem, TallyItem

    Sale.__table__.create(bind=engine, checkfirst=True)
    SaleItem.__table__.create(bind=engine, checkfirst=True)
    TallyItem.__table__.create(bind=engine, checkfirst=True)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "tally_items" in table_names and "product_families" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO tally_items (name, normalized_name, active_status, source, created_at, updated_at)
                    SELECT 
                        tally_stock_item_name, 
                        LOWER(TRIM(tally_stock_item_name)), 
                        'active', 
                        'odbc', 
                        MIN(created_at), 
                        MAX(updated_at)
                    FROM product_families 
                    WHERE category = 'Imported from Tally'
                      AND tally_stock_item_name IS NOT NULL
                      AND TRIM(tally_stock_item_name) != ''
                      AND LOWER(TRIM(tally_stock_item_name)) NOT IN (SELECT normalized_name FROM tally_items WHERE normalized_name IS NOT NULL)
                    GROUP BY LOWER(TRIM(tally_stock_item_name)), tally_stock_item_name
                    """
                )
            )
            
    if "tally_items" in table_names:
        columns = {column["name"] for column in inspector.get_columns("tally_items")}
        if "aliases" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE tally_items ADD COLUMN aliases TEXT"))

    if "label_variants" in table_names:
        columns = {column["name"] for column in inspector.get_columns("label_variants")}
        if "expiry" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE label_variants ADD COLUMN expiry VARCHAR(120)"))
        if "billing_price_missing" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE label_variants ADD COLUMN billing_price_missing BOOLEAN NOT NULL DEFAULT 0"))
        if "extra_field_values" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE label_variants ADD COLUMN extra_field_values TEXT"))

    if "template_masters" in table_names:
        columns = {column["name"] for column in inspector.get_columns("template_masters")}
        if "default_field_values" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE template_masters ADD COLUMN default_field_values TEXT"))
        if "barcode_sample_value" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE template_masters ADD COLUMN barcode_sample_value VARCHAR(120)"))
        if "fields_extracted_file_mtime" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE template_masters ADD COLUMN fields_extracted_file_mtime VARCHAR(80)"))

    if "pos_carts" in table_names:
        columns = {column["name"] for column in inspector.get_columns("pos_carts")}
        additive_columns = {
            "cart_mode": "VARCHAR(40) NOT NULL DEFAULT 'normal'",
            "source_sale_id": "INTEGER",
        }
        for column_name, column_type in additive_columns.items():
            if column_name not in columns:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE pos_carts ADD COLUMN {column_name} {column_type}"))

    if "sales" in table_names:
        columns = {column["name"] for column in inspector.get_columns("sales")}
        if "upi_vpa" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE sales ADD COLUMN upi_vpa TEXT"))

    if "pos_cart_items" in table_names:
        columns_info = inspector.get_columns("pos_cart_items")
        columns = {column["name"] for column in columns_info}
        additive_columns = {
            "item_name_snapshot": "VARCHAR(250)",
            "barcode_snapshot": "VARCHAR(80)",
            "tally_stock_item_name_snapshot": "VARCHAR(250)",
            "mrp_snapshot": "NUMERIC(10, 2)",
            "rate_snapshot": "NUMERIC(10, 2)",
            "source_type": "VARCHAR(40)",
            "is_manual_line": "BOOLEAN NOT NULL DEFAULT 0",
        }
        for column_name, column_type in additive_columns.items():
            if column_name not in columns:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE pos_cart_items ADD COLUMN {column_name} {column_type}"))

        inspector = inspect(engine)
        variant_column = next(
            (column for column in inspector.get_columns("pos_cart_items") if column["name"] == "variant_id"),
            None,
        )
        manual_line_column = next(
            (column for column in inspector.get_columns("pos_cart_items") if column["name"] == "is_manual_line"),
            None,
        )
        manual_line_default = str((manual_line_column or {}).get("default") or "").strip().strip("'\"")
        needs_cart_rebuild = bool(variant_column and not variant_column.get("nullable", True)) or manual_line_default not in {"0", "False", "false"}
        if needs_cart_rebuild:
            with engine.begin() as connection:
                connection.execute(text("PRAGMA foreign_keys=OFF"))
                connection.execute(text("ALTER TABLE pos_cart_items RENAME TO pos_cart_items_old"))
                connection.execute(text("DROP INDEX IF EXISTS ix_pos_cart_items_cart_id"))
                connection.execute(text("DROP INDEX IF EXISTS ix_pos_cart_items_id"))
                connection.execute(text("DROP INDEX IF EXISTS ix_pos_cart_items_variant_id"))
                PosCartItem.__table__.create(bind=connection)
                connection.execute(
                    text(
                        """
                        INSERT INTO pos_cart_items (
                            id, cart_id, variant_id, qty, unit_price,
                            item_name_snapshot, barcode_snapshot, tally_stock_item_name_snapshot,
                            mrp_snapshot, rate_snapshot, source_type, is_manual_line,
                            created_at, updated_at
                        )
                        SELECT
                            old.id,
                            old.cart_id,
                            old.variant_id,
                            old.qty,
                            old.unit_price,
                            COALESCE(old.item_name_snapshot, families.family_name, variants.item_display_name),
                            COALESCE(old.barcode_snapshot, variants.barcode),
                            COALESCE(old.tally_stock_item_name_snapshot, families.tally_stock_item_name),
                            COALESCE(old.mrp_snapshot, variants.mrp),
                            COALESCE(old.rate_snapshot, old.unit_price, variants.selling_price),
                            COALESCE(old.source_type, 'barcode'),
                            COALESCE(old.is_manual_line, 0),
                            old.created_at,
                            old.updated_at
                        FROM pos_cart_items_old old
                        LEFT JOIN label_variants variants ON variants.id = old.variant_id
                        LEFT JOIN product_families families ON families.id = variants.family_id
                        """
                    )
                )
                connection.execute(text("DROP TABLE pos_cart_items_old"))
                connection.execute(text("PRAGMA foreign_keys=ON"))


def _seed_demo_tally_items(db, TallyItem) -> None:
    demo_names = [
        "Demo Tally Shirt",
        "Demo Tally Pant",
        "Demo Tally Socks",
    ]
    existing_names = {
        (item.name or "").strip().lower()
        for item in db.query(TallyItem).all()
    }
    added = False
    for name in demo_names:
        if name.strip().lower() in existing_names:
            continue
        db.add(
            TallyItem(
                name=name,
                normalized_name=name.strip().lower(),
                active_status="active",
                source="demo"
            )
        )
        added = True
    if added:
        db.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
