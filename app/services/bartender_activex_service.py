from __future__ import annotations

from contextlib import contextmanager
import os
import logging
import platform
from pathlib import Path
import sys
import threading
from typing import Any

try:
    import pythoncom  # type: ignore
    from win32com.client import VARIANT  # type: ignore
except ImportError:
    pythoncom = None
    VARIANT = None


logger = logging.getLogger(__name__)


class BarTenderActiveXError(RuntimeError):
    """Raised when BarTender ActiveX field extraction cannot complete."""


def _parse_named_substrings(
    raw_value: Any,
    name_value_separator: str = ",",
    record_separator: str = ":",
) -> list[str]:
    return list(
        _parse_named_substring_values(
            raw_value,
            name_value_separator=name_value_separator,
            record_separator=record_separator,
        )
    )


def _parse_named_substring_values(
    raw_value: Any,
    name_value_separator: str = ",",
    record_separator: str = ":",
) -> dict[str, str]:
    if raw_value is None:
        return {}

    if isinstance(raw_value, (list, tuple)):
        records = [str(item) for item in raw_value]
    else:
        records = str(raw_value).split(record_separator)

    values: dict[str, str] = {}
    for record in records:
        text = record.strip()
        if not text or name_value_separator not in text:
            continue
        field_name, field_value = text.split(name_value_separator, 1)
        field_name = field_name.strip()
        if field_name and field_name not in values:
            values[field_name] = field_value.strip()
    return values


def _do_not_save_value(constants: Any) -> Any:
    for name in ("btDoNotSaveChanges", "BtSaveOptions_btDoNotSaveChanges"):
        try:
            return getattr(constants, name)
        except Exception:
            continue
    return 1


def _close_without_saving(bt_format: Any, constants: Any) -> None:
    if bt_format is None:
        return

    save_option = _do_not_save_value(constants)
    try:
        bt_format.Close(save_option)
        return
    except Exception:
        pass

    try:
        bt_format.Close(False)
    except Exception:
        pass


def _quit_without_saving(bt_app: Any, constants: Any) -> None:
    if bt_app is None:
        return

    save_option = _do_not_save_value(constants)
    try:
        bt_app.Quit(save_option)
        return
    except Exception:
        pass

    try:
        bt_app.Quit()
    except Exception:
        pass


def extract_named_substrings(template_path: str) -> list[str]:
    return list(extract_named_substring_values(template_path))


def _validate_template_path(template_path: str) -> Path:
    if not template_path or not template_path.strip():
        raise BarTenderActiveXError("Template path is missing.")

    path = Path(template_path).expanduser()
    if not path.exists() or not path.is_file():
        raise BarTenderActiveXError(f"Template path is invalid or missing: {path}")
    return path


def _win32com_client() -> Any:
    if os.name != "nt":
        raise BarTenderActiveXError("BarTender ActiveX is only available on Windows.")

    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise BarTenderActiveXError(
            "pywin32 is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return win32com.client


def _dispatch_bartender(win32com_client: Any) -> Any:
    try:
        return win32com_client.Dispatch("BarTender.Application")
    except Exception as exc:
        raise BarTenderActiveXError(
            "BarTender ActiveX Dispatch failed for ProgID 'BarTender.Application'. "
            f"Error: {_exception_detail(exc)}. {_runtime_detail()}."
        ) from exc


def _constant(constants: Any, names: tuple[str, ...], fallback: Any) -> Any:
    for name in names:
        try:
            return getattr(constants, name)
        except Exception:
            continue
    return fallback


def _exception_detail(exc: Exception) -> str:
    parts = [repr(exc)]
    message = str(exc).strip()
    if message and message != repr(exc):
        parts.append(message)
    args = getattr(exc, "args", ())
    if args:
        parts.append(f"args={args!r}")
    return " | ".join(part for part in parts if part)


def _runtime_detail() -> str:
    return (
        f"python={sys.executable}; "
        f"bitness={platform.architecture()[0]}; "
        f"pid={os.getpid()}; "
        f"thread={threading.current_thread().name}"
    )


def _ensure_pythoncom() -> None:
    if pythoncom is None:
        raise BarTenderActiveXError(
            "pywin32 is not installed or pythoncom could not be imported. Run: pip install -r requirements.txt"
        )


def _ensure_preview_com_helpers() -> None:
    _ensure_pythoncom()
    if VARIANT is None:
        raise BarTenderActiveXError(
            "pywin32 preview support is not installed. Run: pip install -r requirements.txt"
        )


def _co_initialize() -> bool:
    _ensure_pythoncom()
    try:
        pythoncom.CoInitialize()
    except Exception as exc:
        raise BarTenderActiveXError(
            f"Could not initialize COM for BarTender automation: {_exception_detail(exc)}. {_runtime_detail()}."
        ) from exc
    return True


def _co_uninitialize(initialized: bool) -> None:
    if not initialized or pythoncom is None:
        return
    try:
        pythoncom.CoUninitialize()
    except Exception:
        pass


@contextmanager
def _com_session():
    initialized = _co_initialize()
    try:
        yield _win32com_client()
    finally:
        _co_uninitialize(initialized)


def _message_variant_detail(messages: Any) -> str:
    try:
        value = messages.value
    except Exception:
        value = None
    return "" if value is None else str(value)


def extract_named_substring_values(template_path: str) -> dict[str, str]:
    path = _validate_template_path(template_path)

    bt_app = None
    bt_format = None

    with _com_session() as win32com_client:
        constants = win32com_client.constants

        try:
            bt_app = _dispatch_bartender(win32com_client)
            bt_app.Visible = False

            try:
                bt_format = bt_app.Formats.Open(str(path), False, "")
            except Exception as exc:
                raise BarTenderActiveXError(f"Could not open BarTender template: {path}") from exc

            try:
                raw_fields = bt_format.NamedSubStrings.GetAll(",", ":")
            except Exception as exc:
                raise BarTenderActiveXError(
                    "Could not read named data sources from this BarTender template."
                ) from exc

            logger.info("BarTender NamedSubStrings.GetAll raw output: %s", raw_fields)
            defaults = _parse_named_substring_values(raw_fields)
            fields = list(defaults)
            logger.info("BarTender parsed named data source fields: %s", fields)
            logger.info("BarTender parsed named data source defaults: %s", defaults)
            if not fields:
                raise BarTenderActiveXError("No named data sources found in this BarTender template.")
            return defaults
        finally:
            _close_without_saving(bt_format, constants)
            _quit_without_saving(bt_app, constants)


def print_with_named_substrings(
    template_path: str,
    values: dict[str, str],
    copies: int,
    visible: bool = False,
) -> dict[str, object]:
    path = _validate_template_path(template_path)

    bt_app = None
    bt_format = None
    copy_count = max(1, int(copies or 1))

    with _com_session() as win32com_client:
        constants = win32com_client.constants

        try:
            bt_app = _dispatch_bartender(win32com_client)
            bt_app.Visible = bool(visible)

            try:
                bt_format = bt_app.Formats.Open(str(path), False, "")
            except Exception as exc:
                raise BarTenderActiveXError(f"Could not open BarTender template: {path}") from exc

            clean_values = {
                str(field_name).strip(): "" if field_value is None else str(field_value)
                for field_name, field_value in values.items()
                if str(field_name).strip()
            }
            for field_name, field_value in clean_values.items():
                try:
                    bt_format.SetNamedSubStringValue(field_name, field_value)
                except Exception as exc:
                    raise BarTenderActiveXError(
                        f"Could not set BarTender field '{field_name}'. Check that the named data source exists in the template."
                    ) from exc

            try:
                bt_format.IdenticalCopiesOfLabel = copy_count
            except Exception as exc:
                raise BarTenderActiveXError(
                    f"Could not set label copies to {copy_count} in BarTender."
                ) from exc

            try:
                result = bt_format.PrintOut(False, False)
            except Exception as exc:
                raise BarTenderActiveXError("BarTender print failed while sending the job.") from exc

            return {
                "mode": "activex",
                "printed": True,
                "copies": copy_count,
                "fields": list(clean_values),
                "result": "" if result is None else str(result),
            }
        finally:
            _close_without_saving(bt_format, constants)
            _quit_without_saving(bt_app, constants)


def print_with_activex(
    template_path: str,
    values: dict[str, str],
    copies: int,
    visible: bool = False,
) -> dict[str, object]:
    return print_with_named_substrings(
        template_path,
        values,
        copies,
        visible=visible,
    )


def export_print_preview_to_image(
    template_path: str,
    values: dict[str, str],
    output_dir: str | Path,
    *,
    visible: bool = False,
    image_type: str = "png",
    dpi: int = 200,
) -> Path:
    path = _validate_template_path(template_path)

    bt_app = None
    bt_format = None
    preview_dir = Path(output_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)
    image_type = "png"
    file_template = "preview_%PageNumber%.png"
    for old_preview in preview_dir.glob("preview_*.png"):
        try:
            old_preview.unlink()
        except OSError:
            pass

    with _com_session() as win32com_client:
        constants = win32com_client.constants

        try:
            bt_app = _dispatch_bartender(win32com_client)
            bt_app.Visible = bool(visible)

            try:
                bt_format = bt_app.Formats.Open(str(path), False, "")
            except Exception as exc:
                raise BarTenderActiveXError(f"Could not open BarTender template: {path}") from exc

            clean_values = {
                str(field_name).strip(): "" if field_value is None else str(field_value)
                for field_name, field_value in values.items()
                if str(field_name).strip()
            }
            for field_name, field_value in clean_values.items():
                try:
                    bt_format.SetNamedSubStringValue(field_name, field_value)
                except Exception as exc:
                    raise BarTenderActiveXError(
                        f"Could not set BarTender field '{field_name}' for preview: {_exception_detail(exc)}"
                    ) from exc

            _ensure_preview_com_helpers()
            msgs = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_DISPATCH, None)

            try:
                result = bt_format.ExportPrintPreviewRangeToImage(
                    "1",
                    str(preview_dir),
                    file_template,
                    "png",
                    4,
                    dpi,
                    16777215,
                    1,
                    True,
                    True,
                    msgs,
                )
            except Exception as exc:
                raise BarTenderActiveXError(
                    "BarTender could not export a preview image with ExportPrintPreviewRangeToImage. "
                    f"Error: {_exception_detail(exc)}. "
                    f"Result: not returned. "
                    f"Messages: {_message_variant_detail(msgs)}. "
                    f"Output dir: {preview_dir}."
                ) from exc

            files = sorted(preview_dir.glob("preview_*.png"))
            if result != 0 or not files:
                raise BarTenderActiveXError(
                    "BarTender preview export did not complete. "
                    f"Result: {result}. "
                    f"Messages: {_message_variant_detail(msgs)}. "
                    f"Output dir: {preview_dir}."
                )
            return files[0]
        finally:
            _close_without_saving(bt_format, constants)
            _quit_without_saving(bt_app, constants)
