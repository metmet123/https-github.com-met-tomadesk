"""Stage F memo layout contract with the application stylesheet applied."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from qt_test_support import close_alert_panel
from ui_theme import scaled_stylesheet


@pytest.mark.parametrize("scale", (1.0, 1.25, 1.5))
@pytest.mark.parametrize("width", (780, 900, 1080, 1330))
def test_memo_layout_contract(width, scale, tmp_path):
    # Qt popup/style objects can outlive a panel and crash construction of the
    # next one in the same process. Keep every width/scale assertion isolated.
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--case", str(width), str(scale), str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _check_layout(width, scale, tmp_path):
    app = QApplication.instance() or QApplication([])
    store = NoteReminderStore(tmp_path / "memo.db")
    note_id = store.create_note("Layout", "First line\nSecond line")
    panel = AlertNotesPanel(store)
    try:
        panel.setStyleSheet(scaled_stylesheet(scale))
        panel.resize(width, 982)
        panel.update_responsive_layout(width)
        panel.show()
        panel.show_note(note_id)
        if scale != 1.0:
            panel.apply_ui_scale(scale)
        app.processEvents()

        editor = panel.editor
        chips = editor.property_chips
        reminder = chips.buttons["reminder"]
        origin_y = reminder.mapTo(panel, QPoint()).y()
        assert chips.layout().sizeHint().width() <= chips.width()
        assert editor.category_button.height() == 28
        for button in chips.buttons.values():
            assert button.height() == 28
            assert button.fontMetrics().horizontalAdvance(button.text()) + 8 <= button.width()

        for turn in range(5):
            chips.buttons["format"].click()
            app.processEvents()
            assert reminder.mapTo(panel, QPoint()).y() == origin_y, (width, scale, turn)
            if turn % 2 == 0:
                toolbar = editor.format_toolbar
                available = toolbar.contentsRect().width()
                for index in (0, 1):
                    needed = toolbar.layout().itemAt(index).layout().sizeHint().width()
                    assert needed <= available, (width, scale, index, needed, available)
                for index in range(toolbar.line_spacing_box.count()):
                    label = toolbar.line_spacing_box.itemText(index)
                    assert toolbar.line_spacing_box.fontMetrics().horizontalAdvance(label) <= (
                        toolbar.line_spacing_box.width() - 21
                    )
                assert editor.content_edit.height() / panel.editor_scroll.viewport().height() >= 0.70
        # Leave the drawer open for the render baseline.
        assert editor.format_panel.isVisible()

        for button in (editor.category_button, editor.manual_save_button,
                       editor.delete_button, *chips.buttons.values()):
            if button.isVisible() and button.text():
                assert button.fontMetrics().horizontalAdvance(button.text()) <= button.width()
        for row in (editor.title_row,):
            for index in range(row.count()):
                widget = row.itemAt(index).widget()
                if widget is None or not widget.isVisible():
                    continue
                point = widget.mapTo(editor, QPoint())
                assert editor.rect().contains(QRect(point, widget.size())), (
                    width, scale, widget.objectName(), point, widget.size()
                )

        listing = panel.list_panel
        assert listing.table.horizontalScrollBar().maximum() == 0
        if listing.width() >= 480:
            assert not listing.table.isColumnHidden(3)
        for combo in (listing.view_combo, listing.sort_combo):
            if combo.isVisible():
                assert combo.width() >= 90

        shot = panel.grab()
        assert not shot.isNull()
        output = os.environ.get("TOMADESK_LAYOUT_SHOTS")
        if output:
            path = Path(output)
            path.mkdir(parents=True, exist_ok=True)
            assert shot.save(str(path / f"memo_{width}_{round(scale * 100)}.png"))
    finally:
        close_alert_panel(panel, app)
        store.close()


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--case":
        raise SystemExit("usage: test_memo_layout_contract.py --case WIDTH SCALE TEMP_DIR")
    _check_layout(int(sys.argv[2]), float(sys.argv[3]), Path(sys.argv[4]))
