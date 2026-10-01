"""Public connection details for the first mobile pairing QR."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap


PAIRING_HEADER = "TOMADESK-PAIR-V1"


def pairing_payload(url: str, fingerprint: str) -> str:
    """Encode only the reachable PC endpoint and TLS pin, never credentials."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or parsed.username or parsed.password
        or parsed.path or parsed.query or parsed.fragment or parsed.port != 47831
    ):
        raise ValueError("올바른 Tailscale 연결 주소가 아닙니다.")
    try:
        host = ipaddress.IPv4Address(parsed.hostname or "")
    except ipaddress.AddressValueError as exc:
        raise ValueError("PC의 Tailscale IPv4 주소를 사용하세요.") from exc
    if host not in ipaddress.ip_network("100.64.0.0/10"):
        raise ValueError("PC의 Tailscale IPv4 주소를 사용하세요.")
    pin = fingerprint.replace(":", "").replace(" ", "").upper()
    if not re.fullmatch(r"[0-9A-F]{64}", pin):
        raise ValueError("인증서 지문은 SHA-256 형식이어야 합니다.")
    return f"{PAIRING_HEADER}\nhttps://{host}:47831\n{pin}"


def pairing_qr(payload: str, size: int = 228) -> QPixmap:
    import qrcode

    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    code.add_data(payload)
    code.make(fit=True)
    matrix = code.get_matrix()
    scale = max(1, size // len(matrix))
    image = QImage(len(matrix) * scale, len(matrix) * scale, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.white)
    painter = QPainter(image)
    try:
        for row, modules in enumerate(matrix):
            for column, dark in enumerate(modules):
                if dark:
                    painter.fillRect(column * scale, row * scale, scale, scale, Qt.GlobalColor.black)
    finally:
        painter.end()
    return QPixmap.fromImage(image)
