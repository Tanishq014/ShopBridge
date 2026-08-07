from app.db import engine
from sqlalchemy import text

def migrate():
    with engine.begin() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pricing_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category VARCHAR(120) UNIQUE,
                    cost_rule_type VARCHAR(40),
                    cost_rule_percent NUMERIC(10, 2),
                    mrp_discount_percent NUMERIC(10, 2),
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """))
            print("Table pricing_rules created.")
        except Exception as e:
            print(f"Error creating pricing_rules: {e}")

        try:
            conn.execute(text("ALTER TABLE product_families ADD COLUMN cost_rule_type VARCHAR(40)"))
            conn.execute(text("ALTER TABLE product_families ADD COLUMN cost_rule_percent NUMERIC(10, 2)"))
            conn.execute(text("ALTER TABLE product_families ADD COLUMN mrp_discount_percent NUMERIC(10, 2)"))
            print("product_families altered.")
        except Exception as e:
            print(f"Error altering product_families: {e}")

        try:
            conn.execute(text("ALTER TABLE receiving_items ADD COLUMN landing_price NUMERIC(10, 2)"))
            conn.execute(text("ALTER TABLE receiving_items ADD COLUMN confirmed_selling_price NUMERIC(10, 2)"))
            conn.execute(text("ALTER TABLE receiving_items ADD COLUMN pricing_rule_applied VARCHAR(200)"))
            conn.execute(text("ALTER TABLE receiving_items ADD COLUMN pricing_confirmed_at DATETIME"))
            print("receiving_items altered.")
        except Exception as e:
            print(f"Error altering receiving_items: {e}")

if __name__ == "__main__":
    migrate()
