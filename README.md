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

- No label should print unless a Label Variant is saved with a non-empty unique barcode.
- New items get a generated barcode before printing.
- Existing items reuse their saved barcode unless `Duplicate / New Price` or `Create new barcode` is used.
- New Stock remembers the last selected category, template, and entry fields in the browser.
- Printing opens a copy picker by default. `Ctrl+P` opens the same picker, and `Print Current Qty` keeps the old direct flow.
- Generated barcode mode is set in Settings as `template_length_safe_alphanumeric`.
- Generated barcode length comes from the selected template's extracted sample barcode when available; otherwise it uses the default length setting.
- Generated barcodes use only `23456789BFGJKLMNQRUVWXY`, uppercase, and avoid consecutive numbers.
- Existing company barcodes can be entered or scanned manually from the advanced barcode field.
- Billing Item and Selling Price are saved on the label record even when BarTender does not print them.

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

Normal printing uses BarTender ActiveX direct print. ShopBridge opens the selected `.btw`, sets named data source values, sets copies, prints without showing the print dialog, then closes without saving the `.btw`.

When a template is saved or fields are extracted, ShopBridge tries to cache a raw BarTender preview image in:

```text
exports\previews\templates\
```

The New Stock page shows that cached raw preview as soon as a template is selected. It can also generate an item-specific BarTender preview image from the selected `.btw` by clicking `Actual Preview`. Preview generation does not print, create a print job, or save changes to the `.btw`.

CSV mode remains available in Settings as a fallback/debug route. CSV fallback files are written in:

```text
print_jobs\
```

Each CSV includes common fields such as barcode, brand, item name, article number, size, MRP, coded price, template path, printer name, and copies.

BarTender mode can also be set before startup with:

```powershell
$env:SHOPBRIDGE_BARTENDER_MODE="activex"
$env:SHOPBRIDGE_SHOW_BARTENDER_WINDOW="false"
```

The BarTender window is hidden by default during normal printing.

The legacy `bartend.exe` command path is kept for debug helpers and can be configured with:

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
- BarTender ActiveX printing does not save changes back into `.btw` files.

## Smoke Checks

Run local barcode/save/print-flow checks without BarTender:

```powershell
.\.venv\Scripts\python scripts\smoke_checks.py
```
