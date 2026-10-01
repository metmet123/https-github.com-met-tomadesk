"""Whole-window drag diagnostics; original databases are opened read-only.

Only this diagnostic process suppresses OS hooks, notifications and backups.
The production window, foreground polling and list event paths remain intact.
"""
import argparse
from collections import defaultdict
from contextlib import ExitStack
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch, MagicMock

from PyQt6.QtCore import QEvent, QTimer
from PyQt6.QtWidgets import QApplication
import main_window
from alert_notes.memo_list import MemoTree
from storage_config import load_storage_paths
from store import Store
from qt_test_support import destroy_widget


class DragApp(QApplication):
    recording = False
    tree = None

    def __init__(self):
        super().__init__([])
        self.samples = defaultdict(list)
        self.drag_count = 0
        self.in_drag = False
        self.previous_tick = perf_counter()
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(16)
        self.heartbeat.timeout.connect(self.tick)
        self.heartbeat.start()

    def tick(self):
        now = perf_counter()
        if self.recording:
            self.samples['heartbeat_drag' if self.in_drag else 'heartbeat_idle'].append(
                (now - self.previous_tick) * 1000)
        self.previous_tick = now

    def notify(self, receiver, event):
        start = perf_counter()
        count = getattr(self, 'drag_count', 0)
        result = super().notify(receiver, event)
        elapsed = (perf_counter() - start) * 1000
        if self.recording and elapsed >= 20 and count == self.drag_count:
            self.samples['slow_' + event.type().name + '_' + type(receiver).__name__].append(elapsed)
        if self.recording and self.tree is not None and receiver in (self.tree, self.tree.viewport()):
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                                QEvent.Type.DragEnter, QEvent.Type.DragMove,
                                QEvent.Type.Drop, QEvent.Type.Paint):
                # The initiating mouse event contains the entire nested drag loop.
                label = 'drag_nested_loop' if count != self.drag_count else event.type().name
                self.samples[label].append(elapsed)
        return result

    def report(self):
        result = {}
        for name, values in self.samples.items():
            values = sorted(values)
            result[name] = {'n': len(values), 'mean_ms': round(sum(values) / len(values), 3),
                            'max_ms': round(values[-1], 3)}
        print('DRAG_REPORT ' + json.dumps({'drags': self.drag_count, 'samples': result}), flush=True)


def backup(source, destination):
    original = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    copied = sqlite3.connect(destination)
    try:
        original.backup(copied)
    finally:
        copied.close()
        original.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seconds', type=int, default=180)
    args = parser.parse_args()
    app = DragApp()
    with TemporaryDirectory(prefix='tomadesk-drag-probe-') as folder, ExitStack() as patches:
        root = Path(folder)
        source = load_storage_paths()[0]
        for name in ('hotkeys.db', 'alert_notes.db'):
            backup(source / name, root / name)
        store = Store(root / 'hotkeys.db')
        for name in ('_configure_explorer_double_click_from_store', '_build_tray',
                     '_create_automatic_backup', 'announce_today_deadlines',
                     '_restore_hidden_windows_on_exit', 'register_hotkeys'):
            patches.enter_context(patch.object(main_window.MainWindow, name, return_value=None))
        for name in ('HotkeyManager', 'WindowsHookRecorder', 'WindowPinController',
                     'TomaPetController', 'AlertService'):
            fake = MagicMock()
            if name == 'HotkeyManager':
                fake.return_value.handle_native_event.return_value = False
            patches.enter_context(patch.object(main_window, name, fake))
        foreground = main_window.foreground_application

        def poll():
            start = perf_counter()
            try:
                return foreground()
            finally:
                if app.recording:
                    app.samples['foreground'].append((perf_counter() - start) * 1000)

        patches.enter_context(patch.object(main_window, 'foreground_application', poll))
        original_drag = MemoTree.startDrag

        def drag(tree, actions):
            app.drag_count += 1
            app.in_drag = True
            print('DRAG_START', flush=True)
            try:
                return original_drag(tree, actions)
            finally:
                app.in_drag = False
                print('DRAG_END', flush=True)
                app.report()

        patches.enter_context(patch.object(MemoTree, 'startDrag', drag))
        window = main_window.MainWindow(store)
        window.setWindowTitle('TomaDesk 드래그 진단 - 전체 창 사본')
        window.resize(1362, 877)
        window._switch_workspace(1)
        app.tree = window.alert_panel.list_panel.table
        window.show()
        app.processEvents()
        app.recording = True
        QTimer.singleShot(max(1, args.seconds) * 1000, window.close)
        print('DRAG_READY readonly_source=True external_effects_suppressed=True', flush=True)
        app.exec()
        app.recording = False
        app.tree = None
        app.report()
        destroy_widget(window, app)
        store.close()
    print('DRAG_CLOSED snapshot_cleaned=True', flush=True)


if __name__ == '__main__':
    main()
