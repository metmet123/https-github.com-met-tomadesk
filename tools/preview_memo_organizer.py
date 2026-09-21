"""Render synthetic organizer previews without touching the user's application database."""
import os
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase
from alert_notes.memo_organizer_panel import OrganizerPanel
from alert_notes.sqlite_store import NoteReminderStore
from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog
from qt_test_support import destroy_widget
from ui_theme import scaled_stylesheet

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/malgun.ttf")
QFontDatabase.addApplicationFont("C:/Windows/Fonts/malgunbd.ttf")
app.setStyleSheet(scaled_stylesheet(1.0))
out = Path(__file__).resolve().parents[1] / "output" / "memo-organizer"
out.mkdir(parents=True, exist_ok=True)
with TemporaryDirectory() as temp:
    store = NoteReminderStore(Path(temp) / "notes.db")
    panel = OrganizerPanel(store)
    panel.resize(1240, 760)
    panel.base.setDate(date(2026, 9, 15))
    panel.input.setPlainText("내일 김팀장한테 견적서 회신해야함 #업무\n금요일까지 3분기 보고서 초안 #업무\n치과 예약 10/2 오후 3시\n아이디어: 고객 온보딩 체크리스트 자동화하면 좋을듯\n프린터 토너 떨어짐\n다음주 화요일 워크숍 장소 알아보기 #업무\n보험 갱신 10월 말")
    panel.capture_input()
    panel.show()
    app.processEvents()
    panel.grab().save(str(out / "review.png"))
    panel.apply_selected()
    panel.views.setCurrentIndex(1)
    app.processEvents()
    panel.grab().save(str(out / "overview.png"))
    panel.views.setCurrentIndex(0)
    panel.resize(850, 680)
    app.processEvents()
    panel.grab().save(str(out / "review-compact.png"))
    dialog = SettingsDialog(HOTKEY_DEFAULTS, "normal", Path(temp), external_ai_store=store)
    dialog.settings_tabs.setCurrentWidget(dialog.external_ai_page)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out / "settings.png"))
    destroy_widget(dialog, app)
    panel.timer.stop()
    destroy_widget(panel, app)
    store.close()
print(out)
