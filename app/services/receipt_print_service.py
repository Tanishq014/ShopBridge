import logging
from typing import Any
from app.models import Sale

logger = logging.getLogger(__name__)



def print_receipt_direct_image(printer_name: str, sale: Sale, receipt_url: str) -> None:


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

        hti.screenshot(url=receipt_url, save_as=img_filename, size=(1000, 10000))

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
            # Crop horizontally to the exact text bounding box, so when it scales to
            # the printer's HORZRES, it fills the entire width perfectly without white space.
            crop_left = max(0, bbox[0] - 30)
            crop_right = min(im.size[0], bbox[2] + 30)
            crop_bottom = min(im.size[1], bbox[3] + 20)
            im = im.crop((crop_left, 0, crop_right, crop_bottom))

            # Debug: Save exact image being sent to printer
            try:
                debug_path = os.path.join(os.getcwd(), "debug_receipt.png")
                im.save(debug_path)
                
                # --- PHYSICAL PAPER SIMULATION ---
                # Simulate a standard 80mm thermal printer (576px) with a 30px hardware deadzone on edges
                sim_paper_width = 576
                sim_deadzone = 30
                
                # Use the EXACT same layout math that the real win32print driver uses below
                sim_safe_margin = 30  # Updated safe margin!
                sim_available_width = sim_paper_width - (sim_safe_margin * 2)
                sim_scale = sim_available_width / im.size[0]
                sim_height = int(im.size[1] * sim_scale)
                
                sim_im = im.resize((sim_available_width, sim_height), Image.Resampling.LANCZOS)
                
                # Create paper canvas
                paper = Image.new('RGBA', (sim_paper_width, sim_height), (255, 255, 255, 255))
                paper.paste(sim_im, (sim_safe_margin, 0))
                
                # Draw red semi-transparent overlays to represent the unprintable hardware margins
                from PIL import ImageDraw
                draw = ImageDraw.Draw(paper, 'RGBA')
                draw.rectangle([(0, 0), (sim_deadzone, sim_height)], fill=(255, 0, 0, 80))
                draw.rectangle([(sim_paper_width - sim_deadzone, 0), (sim_paper_width, sim_height)], fill=(255, 0, 0, 80))
                
                sim_path = os.path.join(os.getcwd(), "debug_receipt_simulated.png")
                # Convert back to RGB for saving as png without transparency issues if opened in simple viewers
                paper.convert('RGB').save(sim_path)
            except Exception as e:
                logger.error(f"Could not save debug receipt: {e}")

        try:
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(printer_name_clean)
        except pywintypes.error as e:
            raise ValueError(
                f"Could not open printer '{printer_name_clean}'. "
                f"Please verify the exact printer name in Windows Control Panel. Error: {e}"
            )

        doc_started = False
        page_started = False
        try:
            hDC.StartDoc("POS Graphical Receipt")
            doc_started = True
            hDC.StartPage()
            page_started = True

            HORZRES = hDC.GetDeviceCaps(win32con.HORZRES)
            LOGPIXELSX = hDC.GetDeviceCaps(win32con.LOGPIXELSX)
            LOGPIXELSY = hDC.GetDeviceCaps(win32con.LOGPIXELSY)

            # Define a safe physical margin for the printer (thermal printers often have unprintable edges)
            safe_margin_px = 30
            available_width = max(100, HORZRES - (safe_margin_px * 2))

            # Base scale to stretch the width to available page width
            scale_x = available_width / im.size[0]
            
            # If the printer has different X and Y DPI (common in thermal printers),
            # we must adjust the Y scale to maintain the correct visual aspect ratio.
            dpi_ratio = LOGPIXELSY / LOGPIXELSX
            scale_y = scale_x * dpi_ratio
            
            scaled_height = int(im.size[1] * scale_y)

            dib = ImageWin.Dib(im)
            dib.draw(hDC.GetHandleOutput(), (safe_margin_px, 0, safe_margin_px + available_width, scaled_height))
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
