from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any


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


def extract_named_substring_values(template_path: str) -> dict[str, str]:
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
