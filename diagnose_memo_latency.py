"""Opt-in real-input diagnostics on a temporary SQLite snapshot, never the source DB."""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch
import cProfile
import io
import json
import pstats
import sqlite3

from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import QApplication
from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore
from storage_config import load_storage_paths
from ui_theme import scaled_stylesheet
from qt_test_support import close_alert_panel


class ProbeApp(QApplication):
    probe = None

    def notify(self, receiver, event):
        result = super().notify(receiver, event)
        p = self.probe
        if (p is not None and p.pending is not None and event.type() == QEvent.Type.Paint
                and receiver is (p.list_panel.table.viewport() if p.pending['action'] == 'move'
                                 else p.editor.content_edit.viewport())):
            data = p.pending
            p.pending = None
            key = 'to_list_paint_ms' if data['action'] == 'move' else 'to_editor_paint_ms'
            data[key] = round((perf_counter() - data.pop('started')) * 1000, 2)
            print('MEMO_REAL_INPUT ' + json.dumps(data, ensure_ascii=True), flush=True)
        return result


class ProbePanel(AlertNotesPanel):
    ready = False
    pending = None

    def run_action(self, label, callback, *args):
        if not self.ready:
            return callback(*args)
        self.parts.clear()
        started = perf_counter()
        profiler = cProfile.Profile() if self.profile_enabled else None
        if profiler:
            profiler.enable()
        try:
            return callback(*args)
        finally:
            if profiler:
                profiler.disable()
            data = {'action': label, 'note_id': self.current_id,
                    'handler_ms': round((perf_counter() - started) * 1000, 2),
                    'parts_ms_inclusive': {k: round(v, 2) for k, v in self.parts.items()}}
            print('MEMO_HANDLER ' + json.dumps(data, ensure_ascii=True), flush=True)
            self.pending = {**data, 'started': started}
            if profiler:
                output = io.StringIO()
                pstats.Stats(profiler, stream=output).strip_dirs().sort_stats('cumulative').print_stats(22)
                print(output.getvalue(), flush=True)

    def select_note(self, note_id):
        return self.run_action('open', super().select_note, note_id)

    def move_note(self, note_id, parent_id, position):
        return self.run_action('move', super().move_note, note_id, parent_id, position)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--quit-after-ms', type=int, default=600000)
    args = parser.parse_args()
    source = load_storage_paths()[0] / 'alert_notes.db'
    app = ProbeApp([])
    with TemporaryDirectory(prefix='tomadesk-memo-probe-') as temporary:
        snapshot = Path(temporary) / 'alert_notes.db'
        original = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
        copied = sqlite3.connect(snapshot)
        try:
            original.backup(copied)
        finally:
            copied.close()
            original.close()
        store = NoteReminderStore(snapshot, '새 메모')
        panel = ProbePanel(store)
        panel.setWindowTitle('TomaDesk 메모 지연 진단 - 임시 사본')
        panel.resize(1362, 877)
        panel.setStyleSheet(scaled_stylesheet(1.0))
        panel.parts = defaultdict(float)
        panel.profile_enabled = args.profile
        with ExitStack() as stack:
            for owner, name, label in (
                (panel.editor, 'set_note', 'editor.set_note'),
                (panel.editor.content_edit, 'set_content', 'body.set_content'),
                (store.memo_data, 'backlinks_for', 'backlinks'),
                (panel.list_panel, 'set_rows', 'list.set_rows'),
                (panel, 'refresh', 'panel.refresh'),
                (panel.calendar, 'refresh', 'calendar.refresh'),
                (panel.reminder_history, 'refresh', 'history.refresh'),
                (panel.summary, 'refresh', 'summary.refresh'),
                (panel, '_finish_version_session', 'version.finish'),
            ):
                def measured(*a, _fn=getattr(owner, name), _label=label, **kw):
                    start = perf_counter()
                    try:
                        return _fn(*a, **kw)
                    finally:
                        panel.parts[_label] += (perf_counter() - start) * 1000
                stack.enter_context(patch.object(owner, name, measured))
            app.probe = panel
            panel.ready = True
            panel.show()
            # Only the diagnostic window expires; the user's running app is untouched.
            QTimer.singleShot(max(1, args.quit_after_ms), app.quit)
            print('PROBE_READY source_readonly=True snapshot_temporary=True profile=' + str(args.profile), flush=True)
            app.exec()
            panel.ready = False
            app.probe = None
            panel.shutdown()
        # Retire timers/widgets before closing their database, like the Qt tests.
        close_alert_panel(panel, app)
        store.close()
    print('PROBE_CLOSED snapshot_cleaned=True', flush=True)


if __name__ == '__main__':
    main()
