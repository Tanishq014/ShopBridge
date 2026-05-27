from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class BarTenderActiveXError(RuntimeError):
    """Raised when BarTender ActiveX field extraction cannot complete."""


def _parse_named_substrings(raw_value: Any, item_separator: str = ",", value_separator: str = ":") -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, (list, tuple)):
        parts = [str(item) for item in raw_value]
    else:
        parts = str(raw_value).split(item_separator)

    fields: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = part.strip()
        if not text:
            continue
        field_name = text.split(value_separator, 1)[0].strip()
        if field_name and field_name not in seen:
            fields.append(field_name)
            seen.add(field_name)
    return fields


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
    if os.name != "nt":
        raise BarTenderActiveXError("BarTender ActiveX extraction is only available on Windows.")

    if not template_path or not template_path.strip():
        raise BarTenderActiveXError("Template path is missing.")

    path = Path(template_path).expanduser()
    if not path.exists() or not path.is_file():
        raise BarTenderActiveXError(f"Template path is invalid or missing: {path}")

    try:
        import win32com.client  # type: ignore
    except ImportError as exc:
        raise BarTenderActiveXError(
            "pywin32 is not installed. Run: pip install -r requirements.txt"
        ) from exc

    bt_app = None
    bt_format = None
    constants = win32com.client.constants

    try:
        try:
            bt_app = win32com.client.Dispatch("BarTender.Application")
        except Exception as exc:
            raise BarTenderActiveXError(
                "BarTender ActiveX is unavailable. Check that BarTender is installed, licensed, and COM automation is registered."
            ) from exc

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

        fields = _parse_named_substrings(raw_fields)
        if not fields:
            raise BarTenderActiveXError("No named data sources found in this BarTender template.")
        return fields
    finally:
        _close_without_saving(bt_format, constants)
        _quit_without_saving(bt_app, constants)
