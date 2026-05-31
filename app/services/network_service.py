from __future__ import annotations

import socket
from urllib.parse import quote


def detected_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
    except OSError:
        return None
    if not ip or ip.startswith("127."):
        return None
    return ip


def scanner_url(request_host: str | None, *, port: int = 8001) -> tuple[str, bool]:
    lan_ip = detected_lan_ip()
    if lan_ip:
        return f"http://{lan_ip}:{port}/scanner", True
    host = (request_host or "").split(":", 1)[0] or "127.0.0.1"
    return f"http://{host}:{port}/scanner", False


def qr_url_for_scanner(scanner: str) -> str:
    return f"/scanner/qr.svg?url={quote(scanner, safe='')}"
