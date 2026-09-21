"""Opt-in frozen-package diagnostics using synthetic data and no global input hooks."""
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import traceback


def run_package_check(report_path: Path) -> int:
    report_path = Path(report_path).resolve()
    # Never overwrite an earlier report, or a file supplied by mistake.
    if report_path.exists():
        return 2
    report_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QFontDatabase
    from PyQt6.QtWidgets import QApplication
    from alert_notes.external_ai_policy import ExternalAIPolicy
    from alert_notes.memo_organizer_panel import OrganizerPanel
    from alert_notes.memo_organizer_store import OrganizerStore
    from alert_notes.sqlite_store import NoteReminderStore
    from alert_notes.toma_pet_assets import TomaSpriteAtlas
    from app_icon import application_icon
    from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog
    from ui_theme import scaled_stylesheet

    app = QApplication.instance() or QApplication([])
    for name in ("malgun.ttf", "malgunbd.ttf"):
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setStyleSheet(scaled_stylesheet(1.0))
    checks = []
    report = {"frozen": bool(getattr(sys, "frozen", False)),
              "utc": datetime.now(timezone.utc).isoformat(), "checks": checks}
    widgets = []

    def require(condition, name):
        if not condition:
            raise RuntimeError(f"Package check failed: {name}")
        checks.append(name)

    def retire(widget):
        widget.hide()
        widget.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        widgets.remove(widget)

    try:
        with TemporaryDirectory(prefix="package-check-", dir=report_path.parent) as temporary:
            db_path = Path(temporary) / "notes.db"
            store = NoteReminderStore(db_path)
            try:
                require(not application_icon().isNull(), "application_icon")
                atlas = TomaSpriteAtlas()
                require(not atlas.action_frame("idle", 0).isNull(), "tomapet_webp_and_metadata")
                policy = ExternalAIPolicy(store)
                require(not policy.allowed, "external_ai_default_blocked")
                panel = OrganizerPanel(store)
                widgets.append(panel)
                panel.resize(1240, 760)
                panel.base.setDate(date(2026, 9, 15))
                raw = "내일 견적서 회신 #업무\n아이디어: 고객 온보딩 자동화\n보험 갱신 10월 말"
                panel.input.setPlainText(raw)
                panel.capture_input()
                require(panel.review.rowCount() == 3, "packaged_organizer_review")
                panel.apply_selected()
                rows = panel.repo.rows()
                require(len(rows) == 3 and sum(bool(row["schedule_id"]) for row in rows) == 1,
                        "local_calendar_registration")
                require(rows[0]["day"] == "2026-09-16", "relative_date_resolution")
                panel.apply_selected()
                require(store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 1,
                        "duplicate_registration_prevented")
                require(not panel.ai_button.isEnabled(), "external_ai_transport_absent")
                # QTableWidget replaces editors with deleteLater(). This check
                # invokes several slots before entering an event loop; flush
                # those retired editors before capturing the visible table.
                app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                panel.show()
                app.processEvents()
                require(panel.grab().save(str(report_path.with_suffix(".review.png"))), "rendered_review")
                panel.views.setCurrentIndex(1)
                app.processEvents()
                require(panel.grab().save(str(report_path.with_suffix(".summary.png"))), "rendered_summary")
                retire(panel)
                for allowed in (True, False):
                    dialog = SettingsDialog(HOTKEY_DEFAULTS, "normal", Path(temporary), external_ai_store=store)
                    widgets.append(dialog)
                    dialog.external_ai_combo.setCurrentIndex(1 if allowed else 0)
                    dialog.accept()
                    require(policy.allowed == allowed, f"settings_saved_{allowed}")
                    retire(dialog)
                before = OrganizerStore(store).rows()
            finally:
                for widget in list(widgets):
                    retire(widget)
                store.close()
            reopened = NoteReminderStore(db_path)
            try:
                require(OrganizerStore(reopened).rows() == before, "database_reopen")
                require(not ExternalAIPolicy(reopened).allowed, "blocked_setting_reopen")
            finally:
                reopened.close()
        report["ok"] = True
    except Exception:
        report["ok"] = False
        report["error"] = traceback.format_exc()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
