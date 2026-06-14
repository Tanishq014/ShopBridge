from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from io import BytesIO
import qrcode
import urllib.parse
from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.config import TEMPLATES_DIR
from app.db import get_db
from app.models import PosCart, Sale, SaleItem
from app.services.template_filters import register_template_filters
from app.services.time_service import LOCAL_TIMEZONE


router = APIRouter(tags=["sales"])
templates = register_template_filters(Jinja2Templates(directory=str(TEMPLATES_DIR)))


def _sale_or_404(db: Session, sale_id: int) -> Sale:
    sale = db.scalar(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(Sale.id == sale_id)
    )
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found.")
    return sale


def _money(value: Decimal | int | str | None) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):.2f}"


def _sale_payload(sale: Sale) -> dict[str, object]:
    items = []
    for item in sale.items:
        items.append(
            {
                "id": item.id,
                "label_variant_id": item.label_variant_id,
                "barcode": item.barcode or "",
                "item_name": item.item_name or "",
                "billing_item": item.item_name or "",
                "tally_stock_item_name": item.tally_stock_item_name or "",
                "mrp": _money(item.mrp),
                "selling_price": _money(item.rate),
                "rate": _money(item.rate),
                "qty": item.qty,
                "amount": _money(item.amount),
                "discount_amount": _money(item.discount_amount),
                "source_type": "barcode" if item.label_variant_id else "tally_item",
                "missing_price": False,
            }
        )
    return {
        "id": sale.id,
        "bill_number": sale.bill_number,
        "status": sale.status,
        "subtotal": _money(sale.subtotal),
        "discount_total": _money(sale.discount_total),
        "round_off": _money(sale.round_off),
        "total": _money(sale.total),
        "payment_mode": sale.payment_mode,
        "notes": sale.notes or "",
        "print_status": sale.print_status,
        "tally_sync_status": sale.tally_sync_status,
        "created_at": sale.created_at.isoformat() if sale.created_at else "",
        "items": items,
        "count": sum(item.qty for item in sale.items),
    }


def _parse_int_ids(values: list[str]) -> list[int]:
    ids: list[int] = []
    for value in values:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _sale_loaded_in_pos(db: Session, sale_id: int) -> bool:
    return db.execute(
        select(PosCart.id).where(
            PosCart.source_sale_id == sale_id,
            PosCart.status.in_(["active", "held"]),
        )
    ).first() is not None


def _unlink_closed_sale_copies(db: Session, sale_id: int) -> None:
    db.execute(
        update(PosCart)
        .where(
            PosCart.source_sale_id == sale_id,
            PosCart.status.notin_(["active", "held"]),
        )
        .values(source_sale_id=None)
    )


@router.post("/sales/{sale_id}/delete")
def delete_sale(sale_id: int, request: Request, db: Session = Depends(get_db)):
    sale = _sale_or_404(db, sale_id)
    if sale.tally_sync_status == "synced":
        return templates.TemplateResponse(request, "sale_detail.html", {"request": request, "sale": sale, "error": "This bill is already synced to Tally. Deleting it may cause inconsistencies. Un-sync or cancel it first."}, status_code=400)

    if _sale_loaded_in_pos(db, sale.id):
        return templates.TemplateResponse(request, "sale_detail.html", {"request": request, "sale": sale, "error": "This bill is currently loaded in POS. Close/cancel that edit first."}, status_code=400)

    _unlink_closed_sale_copies(db, sale.id)
    db.execute(delete(SaleItem).where(SaleItem.sale_id == sale.id))
    db.delete(sale)
    db.commit()
    url = str(request.url_for("list_sales")) + "?deleted=1"
    return RedirectResponse(url, status_code=303)


@router.post("/sales/bulk-delete")
async def bulk_delete_sales(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    sale_ids = _parse_int_ids(form.getlist("sale_ids"))
    if not sale_ids:
        return RedirectResponse("/sales", status_code=303)

    deleted = 0
    skipped = 0
    for sale_id in sale_ids:
        sale = db.get(Sale, sale_id)
        if not sale:
            continue
        if sale.tally_sync_status == "synced":
            skipped += 1
            continue

        if _sale_loaded_in_pos(db, sale.id):
            skipped += 1
            continue

        _unlink_closed_sale_copies(db, sale.id)
        db.execute(delete(SaleItem).where(SaleItem.sale_id == sale.id))
        db.delete(sale)
        deleted += 1

    db.commit()

    url = str(request.url_for("list_sales")) + f"?deleted={deleted}"
    if skipped:
        url += f"&skipped={skipped}"
    return RedirectResponse(url, status_code=303)


@router.get("/sales", response_class=HTMLResponse)
def list_sales(
    request: Request,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    payment_mode: str | None = Query(None),
    bill_number: str | None = Query(None),
    item_search: str | None = Query(None),
    db: Session = Depends(get_db)
):
    q = select(Sale).options(selectinload(Sale.items))

    if start_date:
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=LOCAL_TIMEZONE)
            sd_utc = sd.astimezone(timezone.utc).replace(tzinfo=None)
            q = q.where(Sale.created_at >= sd_utc)
        except ValueError:
            pass

    if end_date:
        try:
            ed = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=LOCAL_TIMEZONE)
            # Filter through the full end date (start of next day)
            ed_next = ed + timedelta(days=1)
            ed_next_utc = ed_next.astimezone(timezone.utc).replace(tzinfo=None)
            q = q.where(Sale.created_at < ed_next_utc)
        except ValueError:
            pass

    if payment_mode:
        q = q.where(Sale.payment_mode == payment_mode)

    if bill_number:
        q = q.where(Sale.bill_number.ilike(f"%{bill_number}%"))

    if item_search:
        term = item_search.strip()
        if term:
            like = f"%{term.lower()}%"
            barcode_prefix = f"{term}%"
            q = q.where(
                exists(
                    select(SaleItem.id).where(
                        SaleItem.sale_id == Sale.id,
                        or_(
                            func.lower(SaleItem.item_name).like(like),
                            func.lower(SaleItem.tally_stock_item_name).like(like),
                            SaleItem.barcode == term,
                            SaleItem.barcode.like(barcode_prefix),
                        ),
                    )
                )
            )

    sales = db.execute(
        q.order_by(Sale.created_at.desc(), Sale.id.desc()).limit(100)
    ).scalars().all()

    return templates.TemplateResponse(
        request,
        "sales.html",
        {
            "request": request,
            "sales": sales,
            "filters": {
                "start_date": start_date or "",
                "end_date": end_date or "",
                "payment_mode": payment_mode or "",
                "bill_number": bill_number or "",
                "item_search": item_search or "",
            }
        },
    )


@router.get("/sales/search-names")
def search_sales_names(q: str = Query(""), db: Session = Depends(get_db)):
    term = q.strip().lower()
    if not term:
        return {"ok": True, "items": []}

    like = f"%{term}%"

    names_q = select(SaleItem.item_name).where(
        func.lower(SaleItem.item_name).like(like),
        SaleItem.item_name != None,
        SaleItem.item_name != ""
    )

    tally_q = select(SaleItem.tally_stock_item_name).where(
        func.lower(SaleItem.tally_stock_item_name).like(like),
        SaleItem.tally_stock_item_name != None,
        SaleItem.tally_stock_item_name != ""
    )

    names = db.execute(names_q).scalars().all()
    tally_names = db.execute(tally_q).scalars().all()

    unique_names = set()
    for name in names + tally_names:
        if name:
            unique_names.add(name.strip())

    sorted_names = sorted(list(unique_names), key=lambda x: x.lower())

    return {"ok": True, "items": sorted_names[:20]}


@router.get("/sales/{sale_id}", response_class=HTMLResponse)
def sale_detail(sale_id: int, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "sale_detail.html",
        {
            "request": request,
            "sale": _sale_or_404(db, sale_id),
        },
    )




@router.post("/sales/{sale_id}/receipt/direct")
def print_sale_receipt_direct(sale_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services.settings_service import get_receipt_printer_name
    from app.services.receipt_print_service import print_receipt_direct, print_receipt_direct_image

    printer_name = get_receipt_printer_name()
    if not printer_name or not printer_name.strip():
        return {"ok": False, "error": "Receipt printer name is not configured."}

    sale = _sale_or_404(db, sale_id)
    receipt_url = str(request.url_for("sale_receipt", sale_id=sale.id)) + "?hide_buttons=1"

    try:
        try:
            print(f"[Direct Print] Attempting image print to {printer_name} for sale {sale.id}")
            print_receipt_direct_image(printer_name, sale, receipt_url=receipt_url)
            print("[Direct Print] Image print successful")
            return {"ok": True, "message": "Receipt sent to printer (Image Mode)"}
        except Exception as img_e:
            print(f"[Direct Print] Image mode failed: {img_e}")
            if sale.upi_vpa:
                return {
                    "ok": False,
                    "error": f"Image direct print failed for UPI receipt, opening browser receipt so QR is preserved. Error: {img_e}",
                }

            # Fallback to ESC/POS text
            print(f"[Direct Print] Falling back to text mode print for sale {sale.id}")
            print_receipt_direct(printer_name, sale)
            print("[Direct Print] Text mode print successful")
            return {"ok": True, "message": f"Receipt sent to printer (Text Mode Fallback). Image mode failed: {img_e}"}
    except Exception as e:
        print(f"[Direct Print] Text mode or general failure: {e}")
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": str(e)}


@router.get("/sales/{sale_id}/receipt", response_class=HTMLResponse)
def sale_receipt(sale_id: int, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "sale_receipt.html",
        {
            "request": request,
            "sale": _sale_or_404(db, sale_id),
        },
    )


@router.get("/sales/{sale_id}/data")
def sale_data(sale_id: int, db: Session = Depends(get_db)):
    sale = _sale_or_404(db, sale_id)
    return {"ok": True, "sale": _sale_payload(sale)}


@router.get("/sales/{sale_id}/upi-qr.png")
def sale_upi_qr(sale_id: int, db: Session = Depends(get_db)):
    sale = _sale_or_404(db, sale_id)
    if not sale.upi_vpa:
        raise HTTPException(status_code=404, detail="No UPI VPA associated with this sale.")

    amount = f"{Decimal(str(sale.total)).quantize(Decimal('0.01')):.2f}"
    name = urllib.parse.quote("Store")
    vpa = urllib.parse.quote(sale.upi_vpa, safe='@')

    upi_url = f"upi://pay?pa={vpa}&pn={name}&am={amount}&cu=INR"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=0,
    )
    qr.add_data(upi_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(content=buf.getvalue(), media_type="image/png")

@router.get("/sales/{sale_id}/receipt/debug-image")
def debug_receipt_image(sale_id: int, request: Request, db: Session = Depends(get_db)):
    sale = _sale_or_404(db, sale_id)
    receipt_url = str(request.url_for("sale_receipt", sale_id=sale.id)) + "?hide_buttons=1"
    
    import os
    import tempfile
    from html2image import Html2Image
    from PIL import Image, ImageChops
    from io import BytesIO
    from fastapi import Response

    with tempfile.TemporaryDirectory() as tmpdirname:
        hti = Html2Image(output_path=tmpdirname)
        edge_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        if os.path.exists(edge_path):
            hti.browser.executable = edge_path

        img_filename = f"receipt_{sale.id}.png"
        img_path = os.path.join(tmpdirname, img_filename)

        hti.screenshot(url=receipt_url, save_as=img_filename, size=(450, 5000))

        if not os.path.exists(img_path):
            return Response("Failed to capture", status_code=500)

        im = Image.open(img_path).convert('RGB')
        bg = Image.new('RGB', im.size, (255, 255, 255))
        diff = ImageChops.difference(im, bg)
        bbox = diff.getbbox()

        if bbox:
            crop_left = max(0, bbox[0] - 5)
            crop_right = min(im.size[0], bbox[2] + 5)
            crop_bottom = min(im.size[1], bbox[3] + 20)
            im = im.crop((crop_left, 0, crop_right, crop_bottom))

        buf = BytesIO()
        im.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.getvalue(), media_type="image/png")
