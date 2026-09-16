"""프로그램 안에서 바로 읽는 사용 설명서.

「도움말」을 누르면 열린다.  한 장에 화면 그림 하나를 놓고 그 위에 번호를
찍은 뒤, 아래에 같은 번호로 설명을 단다.  오른쪽·왼쪽 화살표나 아래 단추로
넘기고, 맨 위 섹션 단추로 원하는 곳으로 곧장 간다.

본문은 :mod:`user_manual_content` 에만 있다.  그림을 다시 캡처하거나 문장을
고칠 때 이 파일은 건드리지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from user_manual_content import MANUAL_SECTIONS, slide_list

def _image_dir() -> Path:
    """단일 EXE로 묶였을 때도 화면 그림을 찾는다.

    PyInstaller는 묶은 자료를 ``sys._MEIPASS`` 아래 풀어 놓는다.  아이콘과
    같은 방식으로 찾아야 배포본에서도 설명서에 그림이 나온다."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "manual"


IMAGE_DIR = _image_dir()
MARKER_COLOR = QColor("#e11d48")
MARKER_TEXT = QColor("#ffffff")
MARKER_RING = QColor("#ffffff")


def _formatted(text: str, hotkeys: dict[str, str]) -> str:
    """``{main_open}`` 같은 자리를 지금 쓰는 실제 키로 바꾼다."""
    try:
        return text.format(**hotkeys)
    except (KeyError, IndexError, ValueError):
        # 본문에 오타가 나도 설명서가 열리지 않는 일은 없어야 한다.
        return text


class AnnotatedShot(QWidget):
    """화면 그림 위에 번호 동그라미를 얹어 그리는 그림판.

    그림은 창 폭에 맞춰 늘이고 줄이되 비율은 그대로 둔다.  마커 좌표는
    0~1 비율이라 어떤 크기로 그려도 같은 곳을 가리킨다.
    """

    def __init__(self, pixmap: QPixmap, markers: list[dict], parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._markers = markers
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(320)

    def hasHeightForWidth(self) -> bool:
        return True

    def _draw_width(self, available: int) -> int:
        """작은 그림은 두 배까지 키운다.

        포스트잇이나 빠른 메모처럼 원래 작은 창은 원본 크기로 두면 번호
        동그라미가 단추를 통째로 덮는다.  글자가 뭉개지지 않는 두 배까지만
        키워서 동그라미가 상대적으로 작아 보이게 한다."""
        if self._pixmap.width() == 0:
            return max(1, available)
        limit = self._pixmap.width() * 2 if self._pixmap.width() < 900 else self._pixmap.width()
        return max(1, min(available, limit))

    def heightForWidth(self, width: int) -> int:
        if self._pixmap.isNull() or self._pixmap.width() == 0:
            return 120
        width = self._draw_width(width)
        return max(1, round(width * self._pixmap.height() / self._pixmap.width()))

    def sizeHint(self) -> QSize:
        width = max(self.minimumWidth(), self.width() or self._pixmap.width())
        return QSize(width, self.heightForWidth(width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 폭이 바뀌면 높이도 따라가야 스크롤 길이가 맞는다.
        self.setFixedHeight(self.heightForWidth(self.width()))

    def _image_rect(self) -> QRect:
        if self._pixmap.isNull():
            return QRect()
        width = self._draw_width(self.width())
        height = self.heightForWidth(self.width())
        left = (self.width() - width) // 2
        return QRect(left, 0, width, height)

    def paintEvent(self, _event) -> None:
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = self._image_rect()
        painter.drawPixmap(rect, self._pixmap)
        painter.setPen(QPen(QColor("#cbd5e1"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))

        radius = 13
        font = QFont(self.font())
        font.setPointSizeF(9.5)
        font.setBold(True)
        painter.setFont(font)
        for index, marker in enumerate(self._markers, start=1):
            center_x = rect.x() + round(rect.width() * float(marker["x"]))
            center_y = rect.y() + round(rect.height() * float(marker["y"]))
            # 그림 가장자리를 가리켜도 동그라미가 잘리지 않게 안으로 끌어온다.
            center_x = min(max(center_x, rect.x() + radius), rect.right() - radius)
            center_y = min(max(center_y, rect.y() + radius), rect.bottom() - radius)
            circle = QRect(center_x - radius, center_y - radius, radius * 2, radius * 2)
            painter.setPen(QPen(MARKER_RING, 2))
            painter.setBrush(MARKER_COLOR)
            painter.drawEllipse(circle)
            painter.setPen(MARKER_TEXT)
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(index))
        painter.end()


class MarkerNote(QFrame):
    """그림의 번호와 짝을 이루는 설명 한 줄."""

    def __init__(self, number: int, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("manualNote")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        badge = QLabel(str(number))
        badge.setObjectName("manualBadge")
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("manualNoteTitle")
        heading.setWordWrap(True)
        text.addWidget(heading)
        detail = QLabel(body)
        detail.setObjectName("manualNoteBody")
        detail.setWordWrap(True)
        text.addWidget(detail)
        layout.addLayout(text, 1)


class UserManualDialog(QDialog):
    """섹션 단추와 좌우 넘기기로 읽는 설명서 창."""

    STYLE = """
    QDialog#userManual { background: #f5f7fb; }
    QLabel#manualTitle { font-size: 21px; font-weight: 700; color: #1f2d55; }
    QLabel#manualLead { font-size: 13px; color: #47536b; }
    QLabel#manualStep { font-size: 12px; font-weight: 700; color: #64748b; }
    QPushButton#manualSection {
        border: 1px solid #d5ddea; border-radius: 15px; padding: 6px 14px;
        background: #ffffff; color: #47536b; font-weight: 700;
    }
    QPushButton#manualSection:hover { background: #eef3ff; }
    QPushButton#manualSection:checked {
        background: #2563eb; border-color: #2563eb; color: #ffffff;
    }
    QFrame#manualStage { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px; }
    QFrame#manualNote { background: #f8fafc; border: 1px solid #e6ebf2; border-radius: 10px; }
    QLabel#manualBadge {
        background: #e11d48; color: #ffffff; border-radius: 13px; font-weight: 700;
    }
    QLabel#manualNoteTitle { font-size: 13px; font-weight: 700; color: #1f2d55; }
    QLabel#manualNoteBody { font-size: 13px; color: #3f4a5f; }
    QFrame#manualBar { background: #ffffff; border-top: 1px solid #e2e8f0; }
    QPushButton#manualNav {
        border: 1px solid #cbd5e1; border-radius: 9px; padding: 7px 18px;
        background: #ffffff; color: #334155; font-weight: 700;
    }
    QPushButton#manualNav:hover { background: #eef3ff; border-color: #93b4fd; }
    QPushButton#manualNav:disabled { color: #b6bfcd; border-color: #e6ebf2; }
    QPushButton#manualPrimary {
        border: 0; border-radius: 9px; padding: 8px 20px;
        background: #2563eb; color: #ffffff; font-weight: 700;
    }
    QPushButton#manualPrimary:hover { background: #1d4ed8; }
    """

    def __init__(self, parent=None, hotkeys: dict[str, str] | None = None):
        super().__init__(parent)
        self._hotkeys = {
            "main_open": "Ctrl+Alt+F10", "tray_hide": "Ctrl+Alt+F11",
            "exit_key": "Ctrl+Alt+F9", "quick_memo": "Ctrl+Alt+N",
            "new_memo": "Ctrl+Alt+Shift+N", "today_view": "Ctrl+Alt+C",
            "memo_search": "Ctrl+Alt+M", "quick_schedule": "Ctrl+Alt+A",
            "record_stop": "Ctrl+Alt+F12", "playback_stop": "Ctrl+Alt+Esc",
        }
        self._hotkeys.update({key: value for key, value in (hotkeys or {}).items() if value})
        self._slides = slide_list()
        self._index = 0
        self._pixmaps: dict[str, QPixmap] = {}

        self.setObjectName("userManual")
        self.setWindowTitle("TomaDesk 사용 설명서")
        self.setStyleSheet(self.STYLE)
        self.resize(1120, 840)
        self.setMinimumSize(760, 560)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 12)
        header_layout.setSpacing(10)
        title = QLabel("TomaDesk 사용 설명서")
        title.setObjectName("manualTitle")
        header_layout.addWidget(title)
        section_row = QHBoxLayout()
        section_row.setSpacing(8)
        self.section_buttons: list[QPushButton] = []
        for index, section in enumerate(MANUAL_SECTIONS):
            button = QPushButton(section["title"])
            button.setObjectName("manualSection")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(section["title"] + " 섹션으로 이동")
            button.clicked.connect(lambda _checked=False, value=index: self._go_section(value))
            self.section_buttons.append(button)
            section_row.addWidget(button)
        section_row.addStretch(1)
        header_layout.addLayout(section_row)
        root.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        bar = QFrame()
        bar.setObjectName("manualBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(22, 12, 22, 12)
        bar_layout.setSpacing(10)
        self.prev_button = QPushButton("◀  이전")
        self.prev_button.setObjectName("manualNav")
        self.prev_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_button.clicked.connect(lambda: self._go(self._index - 1))
        bar_layout.addWidget(self.prev_button)
        self.next_button = QPushButton("다음  ▶")
        self.next_button.setObjectName("manualNav")
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.clicked.connect(lambda: self._go(self._index + 1))
        bar_layout.addWidget(self.next_button)
        self.step_label = QLabel("")
        self.step_label.setObjectName("manualStep")
        bar_layout.addWidget(self.step_label)
        bar_layout.addStretch(1)
        hint = QLabel("← → 방향키로도 넘길 수 있습니다")
        hint.setObjectName("manualStep")
        bar_layout.addWidget(hint)
        close_button = QPushButton("닫기")
        close_button.setObjectName("manualPrimary")
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        bar_layout.addWidget(close_button)
        root.addWidget(bar)

        self._show_slide()

    # ------------------------------------------------------------ 넘기기 --
    def _go(self, index: int) -> None:
        if not self._slides:
            return
        self._index = max(0, min(index, len(self._slides) - 1))
        self._show_slide()

    def _go_section(self, section_index: int) -> None:
        for index, (owner, _slide) in enumerate(self._slides):
            if owner == section_index:
                self._go(index)
                return
        self._sync_sections()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_PageDown):
            self._go(self._index + 1)
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_PageUp):
            self._go(self._index - 1)
            return
        super().keyPressEvent(event)

    # -------------------------------------------------------------- 그리기 --
    def _pixmap(self, name: str) -> QPixmap:
        if name not in self._pixmaps:
            self._pixmaps[name] = QPixmap(str(IMAGE_DIR / name))
        return self._pixmaps[name]

    def _show_slide(self) -> None:
        if not self._slides:
            return
        section_index, slide = self._slides[self._index]
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 14, 22, 20)
        layout.setSpacing(12)

        heading = QLabel(_formatted(slide["title"], self._hotkeys))
        heading.setObjectName("manualTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        lead = QLabel(_formatted(slide.get("lead", ""), self._hotkeys))
        lead.setObjectName("manualLead")
        lead.setWordWrap(True)
        layout.addWidget(lead)

        markers = slide.get("markers", [])
        if slide.get("image"):
            pixmap = self._pixmap(slide["image"])
            stage = QFrame()
            stage.setObjectName("manualStage")
            stage_layout = QVBoxLayout(stage)
            stage_layout.setContentsMargins(12, 12, 12, 12)
            if pixmap.isNull():
                missing = QLabel(f"화면 그림을 찾을 수 없습니다: {slide['image']}")
                missing.setObjectName("manualLead")
                missing.setAlignment(Qt.AlignmentFlag.AlignCenter)
                stage_layout.addWidget(missing)
            else:
                stage_layout.addWidget(AnnotatedShot(pixmap, markers))
            layout.addWidget(stage)

        for number, marker in enumerate(markers, start=1):
            layout.addWidget(MarkerNote(
                number,
                _formatted(marker["title"], self._hotkeys),
                _formatted(marker["body"], self._hotkeys),
            ))
        layout.addStretch(1)

        self.scroll.setWidget(page)
        self.scroll.verticalScrollBar().setValue(0)
        self.step_label.setText(f"{self._index + 1} / {len(self._slides)}")
        self.prev_button.setEnabled(self._index > 0)
        self.next_button.setEnabled(self._index < len(self._slides) - 1)
        self._sync_sections(section_index)

    def _sync_sections(self, current: int | None = None) -> None:
        if current is None and self._slides:
            current = self._slides[self._index][0]
        for index, button in enumerate(self.section_buttons):
            button.setChecked(index == current)
