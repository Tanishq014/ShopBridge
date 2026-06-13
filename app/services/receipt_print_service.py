import logging
from typing import Any
from app.models import Sale

logger = logging.getLogger(__name__)

# ESC/POS Commands
ESC_INIT = b"\x1B\x40"
ESC_ALIGN_LEFT = b"\x1B\x61\x00"
ESC_ALIGN_CENTER = b"\x1B\x61\x01"
ESC_ALIGN_RIGHT = b"\x1B\x61\x02"
ESC_BOLD_ON = b"\x1B\x45\x01"
ESC_BOLD_OFF = b"\x1B\x45\x00"
ESC_DOUBLE_HW = b"\x1D\x21\x11"
ESC_NORMAL_SIZE = b"\x1D\x21\x00"
ESC_CUT = b"\x1D\x56\x00"
LF = b"\x0A"

def format_escpos_receipt(sale: Sale) -> bytes:
    lines = []

    # Header
    lines.append(ESC_INIT)
    lines.append(ESC_ALIGN_CENTER)
    lines.append(ESC_BOLD_ON)
    lines.append(ESC_DOUBLE_HW)
    lines.append(b"BALAJI COS")
    lines.append(ESC_NORMAL_SIZE)
    lines.append(ESC_BOLD_OFF)
    lines.append(LF)

    lines.append(f"Bill No: {sale.bill_number}".encode("utf-8") + LF)

    if sale.created_at:
        local_date = sale.created_at.strftime("%d-%b-%Y %I:%M %p")
        lines.append(f"Date: {local_date}".encode("utf-8") + LF)

    lines.append(ESC_ALIGN_LEFT)
    lines.append(b"--------------------------------" + LF)

    # Items
    for item in sale.items:
        # Check if return
        is_return = item.qty < 0
        qty_str = str(item.qty)
        if is_return:
            qty_str = f"[{item.qty}] (RTN)"

        item_name = str(item.item_name or "ITEM")
        name_part = item_name[:20].ljust(20)
        qty_part = f"{qty_str} x {item.rate:g}"
        lines.append(f"{name_part}".encode("utf-8") + LF)

        amount_part = f"{item.amount:g}".rjust(32)
        lines.append(f"{qty_part}".encode("utf-8") + LF)
        lines.append(amount_part.encode("utf-8") + LF)

    lines.append(b"--------------------------------" + LF)

    # Totals
    lines.append(ESC_ALIGN_RIGHT)
    lines.append(ESC_BOLD_ON)
    lines.append(f"Subtotal: {sale.subtotal:g}".encode("utf-8") + LF)
    if sale.discount_total and sale.discount_total > 0:
        lines.append(f"Discount: -{sale.discount_total:g}".encode("utf-8") + LF)
    if sale.round_off and sale.round_off != 0:
        lines.append(f"Round Off: {sale.round_off:g}".encode("utf-8") + LF)

    lines.append(ESC_DOUBLE_HW)
    lines.append(f"TOTAL: {sale.total:g}".encode("utf-8") + LF)
    lines.append(ESC_NORMAL_SIZE)
    lines.append(ESC_BOLD_OFF)
    lines.append(LF)

    # Payment info
    lines.append(ESC_ALIGN_CENTER)
    pay_mode = (sale.payment_mode or 'cash').upper()
    lines.append(f"Paid via {pay_mode}".encode("utf-8") + LF)

    if sale.upi_vpa:
        lines.append(b"--- UPI PAYMENT INFO ---" + LF)
        lines.append(f"VPA: {sale.upi_vpa}".encode("utf-8") + LF)
        lines.append(b"Pay using this UPI ID" + LF)

    lines.append(LF)
    lines.append(b"Thank you for shopping with us!" + LF)
    lines.append(b"Please visit again." + LF)
    lines.append(LF * 4) # Feed paper

    # Optional cut
    lines.append(ESC_CUT)

    return b"".join(lines)


def print_receipt_direct(printer_name: str, sale: Sale) -> None:
    if not printer_name or not printer_name.strip():
        raise ValueError("Printer name is empty. Cannot print direct.")

    try:
        import win32print
        import pywintypes
    except ImportError:
        raise RuntimeError("pywin32 is not installed. Direct printing requires win32print.")

    receipt_bytes = format_escpos_receipt(sale)
    printer_name_clean = printer_name.strip()

    try:
        hprinter = win32print.OpenPrinter(printer_name_clean)
    except pywintypes.error as e:
        raise ValueError(f"Could not open printer '{printer_name_clean}'. Please verify the exact printer name in Windows Control Panel. Error: {e}")

    doc_started = False
    page_started = False

    try:
        win32print.StartDocPrinter(hprinter, 1, ("POS Receipt", None, "RAW"))
        doc_started = True

        win32print.StartPagePrinter(hprinter)
        page_started = True

        win32print.WritePrinter(hprinter, receipt_bytes)

    finally:
        if page_started:
            try:
                win32print.EndPagePrinter(hprinter)
            except Exception:
                logger.exception("Failed to end receipt printer page")

        if doc_started:
            try:
                win32print.EndDocPrinter(hprinter)
            except Exception:
                logger.exception("Failed to end receipt printer document")

        win32print.ClosePrinter(hprinter)


def print_receipt_direct_image(printer_name: str, sale: Sale, receipt_url: str) -> None:
    if not printer_name or not printer_name.strip():
        raise ValueError("Printer name is empty. Cannot print direct.")

    try:
        from html2image import Html2Image
    except ImportError:
        raise RuntimeError("html2image is not installed. Install it with: pip install html2image")

    try:
        from PIL import Image, ImageWin, ImageChops
    except ImportError:
        raise RuntimeError("Pillow is not installed. Install it with: pip install Pillow")

    try:
        import win32print
        import win32ui
        import win32con
        import pywintypes
    except ImportError:
        raise RuntimeError("pywin32 is not installed. Direct printing requires win32print.")

    printer_name_clean = printer_name.strip()

    # Capture HTML to Image
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdirname:
        hti = Html2Image(output_path=tmpdirname)
        edge_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
        if os.path.exists(edge_path):
            hti.browser.executable = edge_path

        img_filename = f"receipt_{sale.id}.png"
        img_path = os.path.join(tmpdirname, img_filename)

        hti.screenshot(url=receipt_url, save_as=img_filename, size=(576, 5000))

        if not os.path.exists(img_path):
            raise RuntimeError("Failed to capture receipt image.")

        im = Image.open(img_path).convert('RGB')
        bg = Image.new('RGB', im.size, (255, 255, 255))
        diff = ImageChops.difference(im, bg)
        bbox = diff.getbbox()

        if not bbox:
            raise RuntimeError("Receipt screenshot appears blank.")

        if bbox[3] >= im.size[1] - 10:
            raise RuntimeError("Receipt screenshot may be clipped. Use browser receipt fallback.")

        if bbox:
            im = im.crop((0, 0, im.size[0], min(im.size[1], bbox[3] + 20)))

        try:
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(printer_name_clean)
        except pywintypes.error as e:
            raise ValueError(
                f"Could not open printer '{printer_name_clean}'. "
                f"Please verify the exact printer name in Windows Control Panel. Error: {e}"
            )

        HORZRES = hDC.GetDeviceCaps(win32con.HORZRES)
        scale = HORZRES / im.size[0]
        scaled_height = int(im.size[1] * scale)

        doc_started = False
        page_started = False
        try:
            hDC.StartDoc("POS Graphical Receipt")
            doc_started = True
            hDC.StartPage()
            page_started = True

            dib = ImageWin.Dib(im)
            dib.draw(hDC.GetHandleOutput(), (0, 0, HORZRES, scaled_height))
        finally:
            if page_started:
                try:
                    hDC.EndPage()
                except Exception:
                    logger.exception("Failed to end receipt printer page")
            if doc_started:
                try:
                    hDC.EndDoc()
                except Exception:
                    logger.exception("Failed to end receipt printer document")
            hDC.DeleteDC()
