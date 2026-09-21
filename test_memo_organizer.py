import json
import os
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from alert_notes.external_ai_policy import ExternalAIPolicy, KEY
from alert_notes.memo_organizer import analyze, dday
from alert_notes.memo_organizer_panel import OrganizerPanel
from alert_notes.memo_organizer_store import OrganizerStore, STATE_KEY
from alert_notes.sqlite_store import NoteReminderStore
from settings_dialog import HOTKEY_DEFAULTS, SettingsDialog
from qt_test_support import destroy_widget

BASE = date(2026, 9, 15)
SAMPLE = "내일 김팀장한테 견적서 회신해야함\n금요일까지 3분기 보고서 초안\n치과 예약 10/2 오후 3시\n아이디어: 고객 온보딩 체크리스트 자동화하면 좋을듯\n프린터 토너 떨어짐\n다음주 화요일 워크숍 장소 알아보기\n보험 갱신 10월 말"


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def store(tmp_path):
    value = NoteReminderStore(tmp_path / "notes.db")
    yield value
    value.close()


def test_sample_preserves_every_line_and_does_not_invent_work():
    rows = analyze(SAMPLE, BASE)
    assert [r.raw for r in rows] == SAMPLE.splitlines()
    assert [rows[i].day for i in (0, 1, 2, 5)] == ["2026-09-16", "2026-09-18", "2026-10-02", "2026-09-22"]
    assert rows[2].clock == "15:00" and rows[2].kind == "review"
    assert rows[3].kind == "idea"
    assert rows[4].kind == rows[6].kind == "review"
    assert all("후보 3곳" not in row.title and "초안 제출" not in row.title for row in rows)


@pytest.mark.parametrize("raw", ["2/30 회신", "내일 오후 25시 회의", "내일 3시 회의", "답 오면 내일 회신", "매주 화요일 회신", "내일 회신 그리고 모레 제출", "10월 말 보험 갱신", "회의 오후 3시"])
def test_uncertain_inputs_are_not_auto_registered(raw):
    assert analyze(raw, BASE)[0].kind == "review"


def test_short_weekday_and_year_boundary():
    assert analyze("다음주 화 회신", BASE)[0].day == "2026-09-22"
    assert analyze("내일 회신", date(2026, 12, 31))[0].day == "2027-01-01"
    assert analyze("1/2 회신", date(2026, 12, 31))[0].kind == "review"
    assert analyze("2028-02-29 회신", BASE)[0].day == "2028-02-29"


def test_information_and_ideas_are_never_promoted_by_date():
    assert analyze("아이디어: 내일 생각해 볼 앱", BASE)[0].day == ""
    assert analyze("정보: 계약일 10/2", BASE)[0].day == ""


def test_dday_is_live_and_calendar_days():
    assert dday("2026-09-18", BASE) == "D-3"
    assert dday("2026-09-18", date(2026, 9, 18)) == "D-DAY"
    assert dday("2026-09-18", date(2026, 9, 19)) == "D+1"
    assert dday("2026-09-", BASE) == "날짜 확인"


def test_repeated_capture_and_apply_are_idempotent(store):
    repo = OrganizerStore(store)
    identifier = repo.capture("내일 회신 #업무", BASE)
    assert identifier == repo.capture("내일 회신 #업무", BASE)
    values = repo.get_capture(identifier)["items"]
    assert repo.apply(identifier, values) == 1
    assert repo.apply(identifier, values) == 0
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 1
    native = store.schedules.item(repo.rows()[0]["schedule_id"])
    assert native["all_day"] == 1
    assert native["end_at"] == "202609162359"
    assert store.schedules.notifications(native["id"]) == []


def test_ledger_and_schedule_rollback_together(store):
    repo = OrganizerStore(store)
    identifier = repo.capture("내일 회신\n모레 제출", BASE)
    before = store.setting(STATE_KEY)
    with patch.object(repo, "_write", side_effect=RuntimeError("disk failure")):
        with pytest.raises(RuntimeError):
            repo.apply(identifier, repo.get_capture(identifier)["items"])
    assert store.setting(STATE_KEY) == before
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0


def test_invalid_selection_does_not_partially_apply(store):
    repo = OrganizerStore(store)
    identifier = repo.capture("내일 회신\n치과 예약 10/2 오후 3시", BASE)
    rows = repo.get_capture(identifier)["items"]
    rows[1]["kind"] = "event"
    with pytest.raises(ValueError):
        repo.apply(identifier, rows)
    assert store.conn.execute("SELECT COUNT(*) FROM schedule_items").fetchone()[0] == 0


def test_user_supplied_end_allows_appointment_and_explicit_notification(store):
    repo = OrganizerStore(store)
    identifier = repo.capture("치과 예약 10/2 오후 3시", BASE)
    rows = repo.get_capture(identifier)["items"]
    rows[0].update(kind="event", end_clock="16:00", notify=True)
    repo.apply(identifier, rows)
    native = store.schedules.item(repo.rows()[0]["schedule_id"])
    assert native["start_at"] == "202610021500"
    assert native["end_at"] == "202610021600"
    assert store.schedules.notifications(native["id"]) == [0]


def test_local_idea_to_task_is_explicit_and_keeps_identity(store):
    repo = OrganizerStore(store)
    identifier = repo.capture("아이디어: 체크리스트 자동화", BASE)
    rows = repo.get_capture(identifier)["items"]
    repo.apply(identifier, rows)
    assert repo.rows()[0]["kind"] == "idea"
    with pytest.raises(ValueError):
        repo.complete(rows[0]["id"], True)
    rows[0].update(kind="task", day="2026-10-01")
    repo.apply(identifier, rows)
    assert len(repo.rows()) == 1 and repo.rows()[0]["schedule_id"]
    assert repo.rows()[0]["raw"] == "아이디어: 체크리스트 자동화"


def test_calendar_edits_completion_and_deletion_are_authoritative(store):
    repo = OrganizerStore(store)
    identifier = repo.capture("내일 회신", BASE)
    rows = repo.get_capture(identifier)["items"]
    repo.apply(identifier, rows)
    sid = repo.rows()[0]["schedule_id"]
    native = dict(store.schedules.item(sid))
    native.update(title="수정된 회신", start_at="202610010000", end_at="202610020000")
    store.schedules.save_item(native)
    assert repo.rows()[0]["title"] == "수정된 회신"
    assert repo.rows()[0]["day"] == "2026-10-01"
    store.schedules.set_completed(sid, True)
    assert "수정된 회신" not in repo.summary_html(BASE)
    store.schedules.delete_item(sid)
    assert repo.rows() == []
    repo.apply(identifier, rows)
    assert repo.rows() == []


def test_undated_task_completion_persists_and_summary_escapes_html(store):
    repo = OrganizerStore(store)
    identifier = repo.capture("할일: <b>토너</b> 주문\n정보: <script>bad</script>", BASE)
    rows = repo.get_capture(identifier)["items"]
    repo.apply(identifier, rows)
    repo.complete(rows[0]["id"], True)
    assert OrganizerStore(store).rows()[-1]["completed"]
    html = repo.summary_html(BASE)
    assert "토너" not in html and "<script>" not in html and "&lt;script&gt;" in html


def test_backup_database_keeps_capture_and_applied_ids(store, tmp_path):
    repo = OrganizerStore(store)
    identifier = repo.capture("내일 회신\n아이디어: 자동화", BASE)
    repo.apply(identifier, repo.get_capture(identifier)["items"])
    copy = store.backup_database(tmp_path / "copy.db")
    restored = NoteReminderStore(copy)
    try:
        assert OrganizerStore(restored).rows() == repo.rows()
    finally:
        restored.close()


def test_corrupt_state_is_not_silently_overwritten(store):
    store.set_setting(STATE_KEY, "broken")
    with pytest.raises(ValueError):
        OrganizerStore(store).capture("내일 회신", BASE)
    assert store.setting(STATE_KEY) == "broken"


def test_permission_fails_closed_and_neither_mode_has_network(store):
    policy = ExternalAIPolicy(store)
    assert not policy.allowed
    with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
        for value in (False, True):
            policy.save(value)
            identifier = OrganizerStore(store).capture("내일 회신", BASE)
            assert identifier
            with pytest.raises(NotImplementedError if value else PermissionError):
                policy.require_provider()
    store.set_setting(KEY, "yes")
    assert not policy.allowed


def test_settings_cancel_accept_and_reopen(app, store, tmp_path):
    def create():
        return SettingsDialog(HOTKEY_DEFAULTS, "normal", tmp_path, external_ai_store=store)
    dialog = create()
    assert dialog.external_ai_combo.currentData() is False
    dialog.external_ai_combo.setCurrentIndex(1)
    dialog.reject()
    assert not ExternalAIPolicy(store).allowed
    destroy_widget(dialog, app)
    dialog = create()
    dialog.external_ai_combo.setCurrentIndex(1)
    dialog.accept()
    assert ExternalAIPolicy(store).allowed
    destroy_widget(dialog, app)
    dialog = create()
    assert dialog.external_ai_combo.currentData() is True
    dialog.external_ai_combo.setCurrentIndex(0)
    dialog.accept()
    assert not ExternalAIPolicy(store).allowed
    destroy_widget(dialog, app)
    app.processEvents()


def test_ui_capture_review_persist_apply_reopen(app, store):
    panel = OrganizerPanel(store)
    panel.base.setDate(BASE)
    panel.input.setPlainText("내일 회신 #업무\n프린터 토너 떨어짐")
    panel.capture_input()
    assert panel.raw.toPlainText() == panel.input.toPlainText()
    assert panel.review.item(0, 0).checkState() == Qt.CheckState.Checked
    assert panel.review.item(1, 0).checkState() == Qt.CheckState.Unchecked
    panel.review.cellWidget(1, 2).setCurrentIndex(0)  # explicit task
    panel.review.item(1, 1).setText("토너 주문")
    panel.review.item(1, 0).setCheckState(Qt.CheckState.Checked)
    panel.apply_selected()
    assert len(panel.repo.rows()) == 2
    assert panel.repo.rows()[1]["title"] == "토너 주문"
    assert not panel.ai_button.isEnabled()
    panel.timer.stop()
    destroy_widget(panel, app)
    panel = OrganizerPanel(store)
    assert panel.review.item(1, 1).text() == "토너 주문"
    assert "프린터 토너 떨어짐" in panel.raw.toPlainText()
    panel.timer.stop()
    destroy_widget(panel, app)
    app.processEvents()


def test_incomplete_date_edit_does_not_break_overview(app, store):
    panel = OrganizerPanel(store)
    panel.input.setPlainText("내일 회신")
    panel.capture_input()
    panel.review.item(0, 3).setText("2026-09-")
    panel.refresh_overview()
    assert "날짜 확인" in panel.overview.item(0, 3).text()
    panel.timer.stop()
    destroy_widget(panel, app)
    app.processEvents()


def test_existing_dday_convention_is_respected(store):
    repo = OrganizerStore(store)
    store.set_setting("deadline_count_today_as_one", "true")
    assert repo.dday("2026-09-15", BASE) == "D-1"
    assert repo.dday("2026-09-18", BASE) == "D-4"
    assert repo.dday("2026-09-14", BASE) == "D+1"


def test_draft_keeps_original_date_basis_on_reopen(app, store):
    panel = OrganizerPanel(store)
    panel.base.setDate(BASE)
    panel.input.setPlainText("내일 회신")
    destroy_widget(panel, app)
    panel = OrganizerPanel(store)
    assert panel.base.date().toPyDate() == BASE
    assert panel.input.toPlainText() == "내일 회신"
    destroy_widget(panel, app)


def test_full_bundle_roundtrip_keeps_ledger_and_schedule_links(store, tmp_path):
    from alert_notes.database_bundle import export_database_bundle, import_database_bundle
    from alert_notes.sqlite_store import SETTING_COLUMNS
    from alert_notes.schedule_store import ITEM_COLUMNS, NOTIFICATION_COLUMNS
    repo = OrganizerStore(store)
    identifier = repo.capture("내일 회신\n아이디어: 테스트", BASE)
    repo.apply(identifier, repo.get_capture(identifier)["items"])
    tables = {"settings": SETTING_COLUMNS, "schedule_items": ITEM_COLUMNS, "schedule_notifications": NOTIFICATION_COLUMNS}
    path = tmp_path / "bundle.json"
    export_database_bundle({"alert_notes": (store.conn, tables)}, path)
    restored = NoteReminderStore(tmp_path / "restored.db")
    try:
        import_database_bundle({"alert_notes": (restored.conn, tables)}, path)
        assert OrganizerStore(restored).rows() == repo.rows()
    finally:
        restored.close()


def test_organizer_updates_do_not_replace_unsaved_editor_text(app, store):
    from alert_notes.panel import AlertNotesPanel
    from qt_test_support import close_alert_panel
    store.create_note("작성 중인 메모", "원래 내용")
    panel = AlertNotesPanel(store)
    panel.editor.content_edit.setPlainText("아직 저장하지 않은 내용")
    panel.organizer.input.setPlainText("내일 회신")
    panel.organizer.capture_input()
    panel.organizer.apply_selected()
    assert panel.editor.content_edit.toPlainText() == "아직 저장하지 않은 내용"
    panel.organizer.save_snapshot()
    assert panel.editor.content_edit.toPlainText() == "아직 저장하지 않은 내용"
    close_alert_panel(panel, app)
