"""격리된 180개 메모에서 전환/이동 기준 측정. 성능 임계값이나 최적화는 적용하지 않는다."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections import defaultdict
from contextlib import ExitStack
import json
import math
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from time import perf_counter
import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from alert_notes.panel import AlertNotesPanel
from alert_notes.sqlite_store import NoteReminderStore, TOP_LEVEL_PARENT
from qt_test_support import close_alert_panel


class MemoStage1BaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_isolated_selection_and_move_baseline(self):
        with TemporaryDirectory() as folder:
            store = NoteReminderStore(Path(folder) / "notes.db", "새 메모")
            panel = None
            try:
                body = "".join(f"<p>측정 문단 {i}: 메모 내용과 작업 기록</p>" for i in range(80))
                ids = [store.create_note(f"측정 메모 {i}", body) for i in range(180)]
                panel = AlertNotesPanel(store)
                panel.resize(1500, 900)
                panel.show()
                self.app.processEvents()
                samples = defaultdict(list)
                phase = "select"

                def timed(name, function):
                    def wrapped(*args, **kwargs):
                        started = perf_counter()
                        try:
                            return function(*args, **kwargs)
                        finally:
                            samples[f"{phase}.{name}"].append((perf_counter() - started) * 1000)
                    return wrapped

                with ExitStack() as stack:
                    for owner, name, label in (
                        (panel.editor, "set_note", "editor"),
                        (store.memo_data, "backlinks_for", "backlinks"),
                        (panel.list_panel, "set_rows", "list"),
                        (panel, "refresh", "refresh"),
                    ):
                        stack.enter_context(patch.object(owner, name, timed(label, getattr(owner, name))))
                    for phase in ("select", "move"):
                        for i in range(21):
                            started = perf_counter()
                            if phase == "select":
                                panel.select_note(ids[i])
                            else:
                                panel.move_note(ids[i], TOP_LEVEL_PARENT, 0 if i % 2 == 0 else 100)
                            self.app.processEvents()
                            samples[f"{phase}.total"].append((perf_counter() - started) * 1000)

                results = {}
                for name, values in sorted(samples.items()):
                    warm = sorted(values[1:] or values)
                    results[name] = {
                        "calls": len(values), "first_ms": round(values[0], 2),
                        "warm_mean_ms": round(mean(warm), 2),
                        "warm_p95_ms": round(warm[math.ceil(len(warm) * .95) - 1], 2),
                    }
                print("MEMO_BASELINE " + json.dumps({
                    "platform": self.app.platformName(), "notes": 180, "paragraphs_each": 80,
                    "window": [panel.width(), panel.height()], "inclusive_timings": results,
                }, ensure_ascii=True))
                self.assertEqual(len(store.notes()), 180)
                self.assertEqual(store.note(ids[0])["content"], body)
                self.assertEqual(len(samples["select.total"]), 21)
                self.assertEqual(len(samples["move.total"]), 21)
            finally:
                if panel is not None:
                    close_alert_panel(panel, self.app)
                store.close()


if __name__ == "__main__":
    unittest.main()
