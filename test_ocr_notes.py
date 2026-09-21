import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from alert_notes.rich_text import plain_text_from_content
from alert_notes.sqlite_store import NoteReminderStore
from ocr_notes import OcrNoteReview, deadline_candidates, note_content
from screen_ocr import OcrResultDialog

APP = QApplication.instance() or QApplication([])
NOW = datetime(2026, 9, 19, 13, 30)


@pytest.mark.parametrize("text,expected", [
    ("내일 오후 3시 제출", datetime(2026, 9, 20, 15)),
    ("제출 서류\n마감일: 2026-09-30 18:00", datetime(2026, 9, 30, 18)),
    ("날짜 : 10/15 회의", datetime(2026, 10, 15)),
    ("내일 종일 점검", datetime(2026, 9, 20)),
    ("2026-01-01 지난 자료", datetime(2026, 1, 1)),
])
def test_date_candidates(text, expected):
    assert deadline_candidates(text, NOW)[0].due == expected


@pytest.mark.parametrize("text", ["", "그냥 메모 123", "오후 3시 회의", "2월 30일", "매주 월요일 9시", "9월 매출 정리", "보고서에 2026-10-20 날짜가 있음"])
def test_ambiguous_or_unsupported_is_not_suggested(text):
    assert deadline_candidates(text, NOW) == []


def test_candidates_multiple_deduplicated_bounded_and_no_input_mutation():
    text = "내일 회의\n내일 회의\n모레 제출\n" + "x" * 25_000
    assert len(deadline_candidates(text, NOW)) == 2
    assert len(text) > 25_000
    assert not deadline_candidates("a" * 1001 + " 내일\n", NOW)
    assert len(deadline_candidates("\n".join(f"2026-10-{i:02} 회의" for i in range(1, 25)), NOW)) == 10


def test_date_only_does_not_inherit_current_clock():
    candidate = deadline_candidates("내일 제출", NOW)[0]
    assert candidate.due.hour == 0 and candidate.due.minute == 0 and not candidate.has_time


@pytest.fixture
def store(tmp_path):
    store = NoteReminderStore(tmp_path / "notes.db")
    yield store
    store.close()


def test_atomic_new_deadline_preserves_existing_note_and_sync_metadata(store):
    old_id = store.create_note("기존", "편집 중")
    old = dict(store.note(old_id))
    created = store.create_note("OCR", "001\n본문 ", d_day_at="202609201500")
    row = store.note(created)
    assert row["content"] == "001\n본문 " and row["d_day_at"] == "202609201500"
    assert row["d_day_label"] == "OCR" and row["d_day_alert"] == 0
    assert row["sync_id"] and row["revision"] == 1 and row["origin_device_id"]
    assert dict(store.note(old_id)) == old
    assert store.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0


@pytest.mark.parametrize("due", ["202602300000", "202609192500", "2026091", "oops", "２０２６０９１９００００"])
def test_invalid_deadline_never_inserts(store, due):
    with pytest.raises(ValueError):
        store.create_note("OCR", "body", d_day_at=due)
    assert not store.notes()


def test_failed_insert_rolls_back_and_retry_creates_one_note(store):
    store.conn.execute("CREATE TRIGGER reject_ocr BEFORE INSERT ON notes BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    store.conn.commit()
    with pytest.raises(Exception):
        store.create_note("OCR", "body", d_day_at="202609201500")
    assert not store.conn.in_transaction and not store.notes()
    store.conn.execute("DROP TRIGGER reject_ocr")
    store.conn.commit()
    store.create_note("OCR", "body", d_day_at="202609201500")
    assert len(store.notes()) == 1


def test_literal_html_capture_roundtrips_as_text():
    text = '<html><img src="https://example.invalid/private">\n 001 & 내용 </html>'
    assert plain_text_from_content(note_content(text)) == text
    assert note_content(" 001\n원문 ") == " 001\n원문 "


def test_review_cancel_default_multi_select_and_date_edit():
    candidates = deadline_candidates("내일 제출\n모레 점검", NOW)
    review = OcrNoteReview("본문", candidates)
    try:
        save = review.buttons.button(QDialogButtonBox.StandardButton.Save)
        assert not save.isEnabled()
        assert review.buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault()
        review.accept()
        assert review.result() != QDialog.DialogCode.Accepted
        review.candidate_combo.setCurrentIndex(2)
        assert save.isEnabled()
        assert "00:00" in review.date_notice.text()
        review.due_edit.setDateTime(QDateTime(datetime(2026, 10, 1, 17)))
        review.title_edit.setText("확인한 마감")
        assert review.values() == ("확인한 마감", "본문", "202610011700")
        review.title_edit.clear()
        assert not save.isEnabled()
    finally:
        review.close()


@pytest.fixture
def dialog(store):
    dialog = OcrResultDialog(save_note=store.create_note)
    yield dialog
    dialog.close()
    dialog.deleteLater()
    APP.processEvents()


def accept_review(review):
    return QDialog.DialogCode.Accepted


def test_plain_note_uses_edited_text_and_repeated_click_is_idempotent(dialog, store):
    dialog.display("최초 인식")
    dialog.editor.setPlainText("수정한 제목\n 001\n내용 ")
    with patch.object(OcrNoteReview, "exec", accept_review):
        dialog.save_as_note()
        dialog.save_as_note()
        dialog.save_as_note(True)
    assert len(store.notes()) == 1
    row = store.notes()[0]
    assert row["title"] == "수정한 제목"
    assert row["content"] == "수정한 제목\n 001\n내용 "
    assert row["d_day_at"] == ""
    assert APP.clipboard().text() == "최초 인식"  # saving is not a copy operation


def test_deadline_requires_review_and_current_text_is_reparsed(dialog, store):
    dialog.display("내일 오후 3시 제출")
    dialog.recognized_at = NOW
    dialog.refresh_note_actions()
    assert dialog.deadline_button.isEnabled()
    with patch.object(OcrNoteReview, "exec", return_value=QDialog.DialogCode.Rejected):
        dialog.save_as_note(True)
    assert not store.notes() and not dialog.deadline_button.isVisible()
    dialog.display("모레 오전 10시 제출")
    dialog.recognized_at = NOW
    with patch.object(OcrNoteReview, "exec", accept_review):
        dialog.save_as_note(True)
    assert store.notes()[0]["d_day_at"] == "202609211000"


def test_empty_error_processing_and_removed_dates_cannot_save(dialog, store):
    for text, error in [("", False), ("읽는 중", True)]:
        dialog.display(text, error)
        dialog.save_as_note()
    dialog.display("내일 제출")
    dialog.editor.setPlainText("날짜를 지웠음")
    dialog.save_as_note(True)
    assert not store.notes()


def test_cancel_plain_review_and_dismiss_date_make_no_writes(dialog, store):
    dialog.display("내일 제출")
    dialog.dismiss_suggestion()
    dialog.editor.setPlainText("모레 제출")
    dialog.refresh_note_actions()
    assert not dialog.deadline_button.isVisible()
    with patch.object(OcrNoteReview, "exec", return_value=QDialog.DialogCode.Rejected):
        dialog.save_as_note()
    assert not store.notes()


def test_save_failure_keeps_result_retry_success_and_ui_failure_no_duplicate(dialog, store):
    dialog.display("원문\n내일 제출")
    dialog._save_note = Mock(side_effect=OSError("disk full"))
    with patch.object(OcrNoteReview, "exec", accept_review):
        dialog.save_as_note()
        assert "저장하지 못" in dialog.status.text()
        assert dialog.editor.toPlainText() == "원문\n내일 제출"
        assert dialog.memo_button.isEnabled()
        dialog._save_note = store.create_note
        dialog._on_saved = Mock(side_effect=RuntimeError("refresh"))
        dialog.save_as_note()
        dialog.save_as_note()
    assert len(store.notes()) == 1 and "저장됐지만" in dialog.status.text()


def test_main_refresh_does_not_reload_or_save_active_editor():
    from main_window import MainWindow
    from PyQt6.QtCore import QObject
    class ListPanel(QObject):
        def __init__(self):
            super().__init__()
            self.search = SimpleNamespace(text=lambda: "기존검색")
            self.set_rows = Mock(side_effect=lambda *args: self.signalsBlocked() or (_ for _ in ()).throw(AssertionError()))
    panel = SimpleNamespace(list_panel=ListPanel(), current_id=77, editor=Mock(),
                            refresh=Mock(), calendar=Mock(), summary=Mock())
    fake = SimpleNamespace(alert_panel=panel, note_store=Mock(), refresh_deadline_indicators=Mock())
    MainWindow._ocr_note_saved(fake, 123)
    panel.refresh.assert_not_called()
    assert not panel.editor.mock_calls and panel.current_id == 77
    assert not panel.list_panel.signalsBlocked()
    panel.calendar.refresh.assert_called_once()


def test_real_main_editor_manual_draft_survives_new_ocr_note():
    from test_settings_dday_ux import SettingsWindowTest
    case = SettingsWindowTest()
    case.setUpClass()
    case.setUp()
    try:
        window = case.window
        old_id = window.note_store.create_note("기존 메모", "저장된 본문")
        panel = window.alert_panel
        panel.show_note(old_id)
        panel.set_auto_save_enabled(False)
        panel.editor.content_edit.setPlainText("절대 덮어쓰면 안 되는 미저장 본문")
        APP.processEvents()
        before = dict(window.note_store.note(old_id))
        new_id = window.note_store.create_note("OCR", "새 본문", d_day_at="209901010000")
        window._ocr_note_saved(new_id)
        APP.processEvents()
        assert panel.current_id == old_id
        assert panel.editor.content_edit.toPlainText() == "절대 덮어쓰면 안 되는 미저장 본문"
        assert dict(window.note_store.note(old_id)) == before
        assert before["content"] == "저장된 본문"
    finally:
        case.tearDown()


def test_review_does_not_silently_clamp_early_year():
    review = OcrNoteReview("1800-01-01 기록", deadline_candidates("1800-01-01 기록", NOW))
    try:
        assert review.values()[2] == "180001010000"
    finally:
        review.close()
