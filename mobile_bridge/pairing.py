"""Public connection details for the first mobile pairing QR."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlencode,urlsplit

import qrcode

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPainter, QPixmap


def pairing_payload(url: str) -> str:
    """Encode a one-scan app link for the reachable PC endpoint."""
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http" or parsed.username or parsed.password
        or parsed.path or parsed.query or parsed.fragment or parsed.port != 47831
    ):
        raise ValueError("올바른 PC 연결 주소가 아닙니다.")
    try:
        host = ipaddress.IPv4Address(parsed.hostname or "")
    except ipaddress.AddressValueError as exc:
        raise ValueError("PC의 IPv4 주소를 사용하세요.") from exc
    if host.is_loopback or host.is_unspecified or host.is_multicast or host.is_link_local:
        raise ValueError("휴대폰에서 접근할 수 있는 PC IPv4 주소를 사용하세요.")
    return f"tomadesk://pair?{urlencode({'address': f'http://{host}:47831'})}"


def pairing_qr(payload: str, size: int = 228) -> QPixmap:
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
