"""Fixed-size visual samples for the three visible text-format presets."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from .format_presets import load_preset, load_preset_name, preset_summary


def _is_light(color: QColor) -> bool:
    return (0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()) >= 0.8


def preset_sample_icon(data: dict | None, slot: int, size: QSize = QSize(22, 22)) -> QIcon:
    """Draw a readable sample without encoding UI details in saved preset data."""
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = pixmap.rect().adjusted(1, 1, -1, -1)

    if data is None:
        pen = QPen(QColor("#94a3b8"), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 3, 3)
        font = QFont()
        font.setPixelSize(14)
        painter.setFont(font)
        painter.setPen(QColor("#64748b"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "+")
    else:
        color = QColor(str(data.get("color", "#000000")))
        if not color.isValid():
            color = QColor("#000000")
        font = QFont(str(data.get("family", "")))
        font.setPixelSize(14)
        font.setBold(bool(data.get("bold")))
        font.setItalic(bool(data.get("italic")))
        font.setUnderline(bool(data.get("underline")))
        font.setStrikeOut(bool(data.get("strike")))
        if _is_light(color):
            # 흰색·연노랑 서식은 바탕에 묻힌다.  네모 테두리 대신 글자 자체에
            # 회색 외곽선을 둘러 모양이 보이게 한다.
            metrics = QFontMetricsF(font)
            advance = metrics.horizontalAdvance("가")
            x = rect.x() + (rect.width() - advance) / 2
            y = rect.y() + (rect.height() + metrics.ascent() - metrics.descent()) / 2 - 1
            path = QPainterPath()
            path.addText(x, y, font, "가")
            painter.setPen(QPen(QColor("#94a3b8"), 1.4, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.fillPath(path, color)
            if font.underline() or font.strikeOut():
                painter.setFont(font)
                painter.setPen(QColor("#94a3b8"))
                painter.drawText(rect.adjusted(0, -1, 0, 0), Qt.AlignmentFlag.AlignCenter, "\u3000")
        else:
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(rect.adjusted(0, -1, 0, 0), Qt.AlignmentFlag.AlignCenter, "가")

    number_font = QFont()
    number_font.setPixelSize(7)
    painter.setFont(number_font)
    painter.setPen(QColor("#94a3b8"))
    painter.drawText(rect.adjusted(0, 0, -1, -1), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, str(slot))
    painter.end()
    return QIcon(pixmap)


class PresetStrip(QWidget):
    apply_requested = pyqtSignal(int)
    menu_requested = pyqtSignal(int, QPoint)

    def __init__(self, parent=None, button_size: int = 26):
        super().__init__(parent)
        self.setObjectName("formatPresetStrip")
        # 세 칸이 한 묶음으로 보이도록 바깥 테두리는 묶음에만, 칸 사이는 선 하나.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#formatPresetStrip{background:#ffffff;border:1px solid #cbd5e1;border-radius:7px;}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(1, 1, 1, 1)
        row.setSpacing(0)
        self.buttons: dict[int, QToolButton] = {}
        for slot in range(1, 4):
            button = QToolButton(self)
            button.setObjectName("formatPresetSample")
            button.setCheckable(True)
            button.setProperty("presetSlot", slot)
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.clicked.connect(lambda _checked=False, value=slot: self.apply_requested.emit(value))
            button.customContextMenuRequested.connect(
                lambda pos, value=slot, target=button: self.menu_requested.emit(value, target.mapToGlobal(pos))
            )
            row.addWidget(button)
            self.buttons[slot] = button
        self.set_button_size(button_size)

    def set_button_size(self, button_size: int) -> None:
        self.button_size = int(button_size)
        size = self.button_size
        for slot, button in self.buttons.items():
            divider = "border-left:1px solid #e2e8f0;" if slot > 1 else ""
            inner = size - 1 if slot > 1 else size
            button.setFixedSize(size, size)
            button.setStyleSheet(
                f"QToolButton{{border:0;{divider}border-radius:0;background:transparent;padding:0;"
                f"min-width:{inner}px;max-width:{inner}px;min-height:{size}px;max-height:{size}px;}}"
                "QToolButton:hover{background:#f1f5f9;}"
                "QToolButton:checked{background:#dbe7ff;}"
            )
            icon = max(16, size - 4)
            button.setIconSize(QSize(icon, icon))
        self.setFixedSize(size * len(self.buttons) + 2, size + 2)
        if getattr(self, "_store", None) is not None:
            self.reload(self._store)

    def reload(self, store) -> None:
        self._store = store
        for slot, button in self.buttons.items():
            data = load_preset(store, slot)
            name = load_preset_name(store, slot) or f"서식 {slot}"
            summary = preset_summary(data)
            button.setIcon(preset_sample_icon(data, slot, button.iconSize()))
            button.setToolTip(f"{name}\n{summary}\n클릭: 적용 · 우클릭: 관리")
            button.setAccessibleName(name)
            button.setAccessibleDescription(summary)

    def set_active(self, slot: int | None) -> None:
        for value, button in self.buttons.items():
            button.blockSignals(True)
            button.setChecked(value == slot)
            button.blockSignals(False)
            name = button.toolTip().splitlines()[0] if button.toolTip() else f"서식 {value}"
            button.setAccessibleName(f"{name} {'선택됨' if value == slot else '선택 안 됨'}")
