"""Qt lifecycle for workspace panels and asynchronous Explorer navigation."""

import copy
import json

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog

from action_runner import _layout_state_key
from layout_favorites_panel import FavoritesDialog, FavoritesPanel
from layout_workspace import WorkspaceRuntime, workspace_payload, window_is_uncovered
from window_layout import (
    absolute_rect, collect_open_windows, enumerate_monitors,
)


class NavigationWorker(QThread):
    completed = pyqtSignal(str, str)

    def __init__(self, runtime, record, path, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self.record = record
        self.path = path

    def run(self):
        try:
            path = self.runtime.navigator(self.record["hwnd"], self.path, self.runtime.ownership, self.record["token"])
        except Exception as exc:
            self.completed.emit("", str(exc))
        else:
            self.completed.emit(path, "")


class WorkspaceController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.runtime = WorkspaceRuntime(window.runner)
        self.contexts = {}
        self.panel_handles = frozenset()
        self.worker = None
        self.busy_key = None
        self.closed = False
        window.runner.workspace_handler = self.execute
        window.runner.workspace_hide_handler = self.hide_for_window
        window.runner.workspace_reserved_handles = self.reserved_handles

    def _context(self, key, payload, action_id):
        row = self.window.store.action(action_id) if action_id is not None else None
        name = row["name"] if row is not None else "미저장 창배치"
        ctx = self.contexts.get(key)
        if ctx is None:
            panel = FavoritesPanel()
            panel.folder_requested.connect(lambda slot, path, k=key: self.navigate(k, slot, path))
            panel.manage_requested.connect(lambda k=key: self.manage_favorites(k))
            panel.save_geometry_requested.connect(lambda k=key: self.save_geometry(k))
            ctx = {"panel": panel, "id": action_id, "key": key}
            self.contexts[key] = ctx
            self.panel_handles = frozenset(int(c["panel"].winId()) for c in self.contexts.values())
        elif ctx["payload"]["workspace"]["target_slot"] != payload["workspace"]["target_slot"]:
            ctx["panel"].target.clear()
        ctx.update(payload=payload, name=name)
        ctx["panel"].apply_scale(getattr(self.window, "_ui_scale", 1.0))
        ctx["panel"].configure(name, payload)
        return ctx

    def _panel_rect(self, payload):
        geometry = payload["workspace"].get("geometry")
        if not isinstance(geometry, dict) or not isinstance(geometry.get("rect"), list) or len(geometry["rect"]) != 4:
            return None
        monitors = enumerate_monitors()
        monitor = next((m for m in monitors if m["device"] == geometry.get("monitor_device")), None)
        monitor = monitor or next((m for m in monitors if m["number"] == geometry.get("monitor")), None)
        monitor = monitor or next(iter(monitors), None)
        if monitor:
            return absolute_rect(geometry["rect"], monitor["work_rect"], geometry.get("dpi", 96), monitor["dpi"])
        return None

    def _panel_ready(self, panel, payload, ignored):
        if not panel.isVisible() or panel.isMinimized():
            return False
        rect = self._panel_rect(payload)
        if rect and any(abs(a - b) > 8 for a, b in zip(panel.geometry().getRect(), rect)):
            return False
        return window_is_uncovered(int(panel.winId()), ignored)

    def execute(self, payload, action_id=None):
        if self.closed:
            raise RuntimeError("앱이 종료 중입니다.")
        options = payload.get("workspace", {})
        if not isinstance(options, dict) or not options.get("enabled"):
            key = _layout_state_key(payload, action_id)
            if key in self.contexts:
                self.deactivate(key)
            return None
        if self.busy_key is not None:
            return "폴더 이동 중입니다. 완료 후 다시 실행해 주세요."
        payload = workspace_payload(payload)
        key = _layout_state_key(payload, action_id)
        ctx = self._context(key, payload, action_id)
        panel = ctx["panel"]
        group = self.runtime.refresh(key, payload)
        ignored = {int(panel.winId())} | {r["hwnd"] for r in group.values()}
        if self._panel_ready(panel, payload, ignored) and self.runtime.at_layout(key, payload, ignored):
            errors = self.runtime.hide(key, payload)
            if not errors:
                panel.hide()
            return self._result(key, "숨김", errors)
        errors = self.runtime.show(key, payload)
        rect = self._panel_rect(payload)
        if rect:
            panel.setGeometry(*rect)
        panel.showNormal()
        panel.raise_()
        # Give Explorer activation to the target last, without a permanent pin.
        slot = panel.target.currentData()
        target = self.runtime.groups.get(key, {}).get(slot)
        if target:
            self.window.runner._window_activator(target["hwnd"])
        if errors:
            panel.message.setText("일부 창 복원 실패: " + "; ".join(errors))
        return self._result(key, "복원", errors)

    def _result(self, key, action, errors):
        count = len(self.runtime.groups.get(key, {}))
        if errors:
            return f"{count}개 대상 창 · {action} 일부 실패 · 즐겨찾기 패널: " + "; ".join(errors)
        return f"{count}개 창 {action} · 즐겨찾기 패널"

    def hide_for_window(self, hwnd):
        if self.busy_key is not None:
            return None
        for key, ctx in self.contexts.items():
            group = self.runtime.refresh(key, ctx["payload"])
            if any(r["hwnd"] == hwnd for r in group.values()):
                errors = self.runtime.hide(key, ctx["payload"])
                if not errors:
                    ctx["panel"].hide()
                return self._result(key, "숨김", errors)
        return None

    def navigate(self, key, slot, path):
        if self.closed or self.busy_key is not None:
            return
        ctx = self.contexts[key]
        panel = ctx["panel"]
        self.busy_key = key
        panel.set_busy(True)
        try:
            record = self.runtime.navigation_target(key, ctx["payload"], slot, path)
        except Exception as exc:
            self.busy_key = None
            panel.set_busy(False)
            panel.message.setText(str(exc))
            return
        worker = NavigationWorker(self.runtime, record, path, self)
        self.worker = worker
        worker.completed.connect(lambda actual, error, k=key: self._navigation_done(k, actual, error))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _navigation_done(self, key, actual, error):
        if self.closed:
            return
        ctx = self.contexts[key]
        try:
            self.runtime.refresh(key, ctx["payload"])
            self.runtime.persist(key)
            if actual:
                group = self.runtime.groups.get(key, {})
                target = next((r for r in group.values() if r["hwnd"] == self.worker.record["hwnd"]), None)
                if target:
                    self.window.runner._window_activator(target["hwnd"])
        except Exception as exc:
            error = str(exc)
        finally:
            self.busy_key = None
            ctx["panel"].set_busy(False)
        ctx["panel"].message.setText(error or "열었습니다: " + actual)

    def _save_payload(self, key, payload, fields):
        ctx = self.contexts[key]
        row = self.window.store.action(ctx["id"]) if ctx["id"] is not None else None
        if row is None:
            raise ValueError("창배치 작업을 먼저 저장한 뒤 다시 실행해 주세요.")
        data = dict(row)
        current = workspace_payload(json.loads(row["payload"]))
        for field in fields:
            current["workspace"][field] = copy.deepcopy(payload["workspace"][field])
        if "geometry" in fields:
            positions = {e["slot_id"]: e for e in payload["windows"]}
            for entry in current["windows"]:
                if entry["slot_id"] in positions:
                    entry.update({f: copy.deepcopy(positions[entry["slot_id"]][f]) for f in ("monitor", "monitor_device", "rect", "rect_basis", "state", "work_area", "dpi") if f in positions[entry["slot_id"]]})
        data["payload"] = current
        self.window.store.save_action(data)
        ctx["payload"] = current
        ctx["panel"].configure(ctx["name"], ctx["payload"])
        if self.window.current_id == ctx["id"] and self.window._action_form_baseline is not None:
            # Only mark fields actually saved by the panel as clean.
            baseline = self.window._action_form_baseline
            options = copy.deepcopy(baseline.get("layout_workspace", {}))
            for field in fields:
                options[field] = copy.deepcopy(current["workspace"][field])
            baseline["layout_workspace"] = options
            if "geometry" in fields:
                positions = {e["slot_id"]: e for e in current["windows"]}
                for entry in baseline.get("layout_windows", []):
                    saved = positions.get(entry.get("slot_id"))
                    if saved:
                        entry.update({f: copy.deepcopy(saved[f]) for f in ("monitor", "monitor_device", "rect", "rect_basis", "state", "work_area", "dpi") if f in saved})

    def manage_favorites(self, key):
        if self.busy_key is not None:
            return
        ctx = self.contexts[key]
        dialog = FavoritesDialog(ctx["payload"]["workspace"]["favorites"], ctx["panel"])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            payload = copy.deepcopy(ctx["payload"])
            payload["workspace"]["favorites"] = dialog.favorites()
            self._save_payload(key, payload, ("favorites",))
            if self.window.current_id == ctx["id"]:
                self.window.layout_workspace_settings.options["favorites"] = dialog.favorites()
            ctx["panel"].message.setText("즐겨찾기를 저장했습니다.")
        except Exception as exc:
            ctx["panel"].message.setText(str(exc))

    def save_geometry(self, key):
        if self.busy_key is not None:
            return
        ctx = self.contexts[key]
        try:
            group = self.runtime.refresh(key, ctx["payload"])
            captured = {int(item["hwnd"]): item for item in collect_open_windows()}
            payload = copy.deepcopy(ctx["payload"])
            if len(group) != len(payload["windows"]):
                raise ValueError("모든 대상 탐색기를 표시한 뒤 위치를 저장해 주세요.")
            fields = ("monitor", "monitor_device", "rect", "rect_basis", "state", "work_area", "dpi")
            for entry in payload["windows"]:
                item = captured.get(group[entry["slot_id"]]["hwnd"])
                if item is None:
                    raise ValueError("모든 대상 탐색기를 표시한 뒤 위치를 저장해 주세요.")
                entry.update({field: copy.deepcopy(item[field]) for field in fields if field in item})
            panel = ctx["panel"]
            item = captured.get(int(panel.winId()))
            if item is None:
                raise ValueError("즐겨찾기 패널 위치를 조회하지 못했습니다.")
            # QWidget geometry is its client rectangle; store that coordinate basis.
            monitor = next((m for m in enumerate_monitors() if m["number"] == item["monitor"]), None)
            if monitor is None:
                raise ValueError("패널 모니터를 조회하지 못했습니다.")
            geometry = {field: copy.deepcopy(item[field]) for field in fields if field in item}
            geometry["rect"] = [panel.geometry().x() - monitor["work_rect"][0], panel.geometry().y() - monitor["work_rect"][1], panel.width(), panel.height()]
            geometry["rect_basis"] = "client"
            payload["workspace"]["geometry"] = geometry
            self._save_payload(key, payload, ("geometry",))
            # Preserve unsaved names/settings while updating only captured geometry.
            if self.window.current_id == ctx["id"]:
                positions = {entry["slot_id"]: entry for entry in payload["windows"]}
                rows = self.window._layout_row_states()
                for entry in rows:
                    saved = positions.get(entry.get("slot_id"))
                    if saved:
                        entry.update({f: copy.deepcopy(saved[f]) for f in fields if f in saved})
                self.window._set_layout_rows(rows)
                self.window.layout_workspace_settings.options["geometry"] = geometry
            ctx["panel"].message.setText("현재 위치·크기를 저장했습니다. 초기 폴더는 유지했습니다.")
        except Exception as exc:
            ctx["panel"].message.setText(str(exc))

    def apply_scale(self, scale):
        for ctx in self.contexts.values():
            ctx["panel"].apply_scale(scale)

    def reserved_handles(self, key):
        return {r["hwnd"] for other, group in self.runtime.groups.items() if other != key for r in group.values() if self.runtime.ownership.valid(r["hwnd"], r["token"])}

    def deactivate(self, key):
        ctx = self.contexts[key]
        group = self.runtime.refresh(key, ctx["payload"])
        for record in group.values():
            if record.get("hidden"):
                if not self.window.runner._window_shower(record["hwnd"], record["path"]):
                    raise RuntimeError("즐겨찾기 배치의 숨긴 창을 복원하지 못했습니다.")
                record["hidden"] = False
        self.runtime.persist(key)
        for record in group.values():
            self.runtime.ownership.release(record["hwnd"], record["token"])
        self.runtime.groups.pop(key, None)
        ctx["panel"].hide()
        ctx["panel"].deleteLater()
        self.contexts.pop(key)
        self.panel_handles = frozenset(int(c["panel"].winId()) for c in self.contexts.values())

    def remove_actions(self, action_ids):
        if self.busy_key in {f"action:{action_id}" for action_id in action_ids}:
            raise ValueError("폴더 이동 완료 후 창배치 작업을 삭제해 주세요.")
        for action_id in action_ids:
            key = f"action:{action_id}"
            if key in self.contexts:
                self.deactivate(key)
                self.window.runner._save_layout_records(key, [])

    def sync_saved(self, action_id, action_type, payload):
        key = _layout_state_key(payload, action_id)
        if key not in self.contexts:
            return
        if action_type != "layout" or not payload.get("workspace", {}).get("enabled"):
            self.deactivate(key)
            return
        payload = workspace_payload(payload)
        self.runtime.refresh(key, payload)
        self.runtime.persist(key)
        self._context(key, payload, action_id)

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.panel_handles = frozenset()
        if self.worker is not None:
            try:
                self.worker.wait()
            except RuntimeError:
                pass  # Completed workers may already be deleted by Qt.
        for key, ctx in self.contexts.items():
            try:
                self.runtime.refresh(key, ctx["payload"])
                self.runtime.persist(key)
            except Exception:
                pass  # Existing persistent recovery records remain intact.
            ctx["panel"].hide()
            ctx["panel"].deleteLater()
        self.runtime.shutdown()
