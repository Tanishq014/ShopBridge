# ShopBridge

ShopBridge is a local Windows barcode and label manager for a shop that bills in Tally.ERP 9 and prints through BarTender.

Version one is intentionally read-only toward Tally. It can test/read Tally ODBC data and import stock item names into ShopBridge Product Families, but it does not write XML, vouchers, stock items, or any other data back to live Tally.

## Setup

Run these commands from the `shopbridge` folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

The SQLite database is created on first startup at:

```text
data\shopbridge.db
```

## Core Model

- Product Family: broad billing item, often matching a Tally stock item.
- Label Variant: exact sticker and barcode identity.
- Template Master: maps a template id to a BarTender `.btw` path, printer name, and required fields.
- Print Job: stores a request to print a variant with a selected template and copy count.

## Barcode Rules

- Internal generated barcodes start at `240000000001`.
- Generated barcodes are unique in ShopBridge.
- Existing company barcodes can be entered or scanned manually.

## Coded Price

Coded price is generated from `selling_price` when the field is left blank on a variant.

The current digit mapping is in:

```text
app\services\price_code_service.py
```

Change `PRICE_CODE_DIGITS` there if the shop wants a different private code.

## BarTender

BarTender remains responsible for actual label design and printing.

Put `.btw` files here:

```text
bartender_templates\
```

ShopBridge scans that folder on startup and when opening Settings or New Stock. Imported templates start with no required fields until you click `Extract from BarTender template` or manually tick fields in Settings. Label size, margins, logo position, barcode position, and saved printer setup stay inside the `.btw` file.

This MVP creates CSV files in:

```text
print_jobs\
```

Each CSV includes common fields such as barcode, brand, item name, article number, size, MRP, coded price, template path, printer name, and copies.

The service also contains a future `run_bartend_exe()` function in:

```text
app\services\bartender_service.py
```

It is not called automatically yet.

The BarTender executable path can be configured with:

```powershell
$env:SHOPBRIDGE_BARTEND_EXE_PATH="C:\Program Files (x86)\Seagull\BarTender Suite\bartend.exe"
```

## Tally ODBC

The Tally page can:

- show ODBC DSNs reported by `pyodbc`
- test the default DSN `TallyODBC64_9000`
- list table names if the DSN connects
- attempt to import stock item names into Product Families

Tally import is read-only. It only reads names and creates missing rows in the local SQLite database.

If Tally uses a different DSN:

```powershell
$env:SHOPBRIDGE_TALLY_DSN="YourDsnName"
```

## Safety

- No writes to live Tally.
- No Tally XML import.
- No hard delete routes. Records are deactivated or marked inactive/cancelled.
- BarTender printing is staged through CSV files first.
