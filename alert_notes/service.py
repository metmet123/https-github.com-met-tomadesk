from collections import deque

from PyQt6.QtCore import QObject, QTimer

from .alert_dialog import ReminderAlertDialog, ScheduleAlertDialog
from .note_shortcuts import modifier_setting
from .toma_pet_alert import TomaPetAlertDialog


class AlertService(QObject):
    """Poll due reminders and display a single dialog at a time."""

    def __init__(
        self, store, open_note_callback, refresh_callback=None,
        open_schedule_callback=None, parent=None, pet_controller=None,
    ):
        super().__init__(parent)
        self.store = store
        self.open_note_callback = open_note_callback
        self.refresh_callback = refresh_callback or (lambda: None)
        self.open_schedule_callback = open_schedule_callback or (lambda _item_id: None)
        self.pet_controller = pet_controller
        self.queue = deque()
        self.queued_ids: set[int] = set()
        self.active_dialog = None
        self._running = False
        self._pause_depth = 0
        self._stopped = False
        self.timer = QTimer(self)
        self.timer.setInterval(20_000)
        self.timer.timeout.connect(self.check_now)
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.setInterval(1000)
        self.startup_timer.timeout.connect(self.check_now)

    def start(self) -> None:
        self._running = True
        self._stopped = False
        if self._pause_depth:
            return
        self.timer.start()
        self.startup_timer.start()

    def stop(self) -> None:
        self._running = False
        self._stopped = True
        self._pause_depth = 0
        self.timer.stop()
        self.startup_timer.stop()
        if self.active_dialog is not None:
            self.active_dialog.close()
            self.active_dialog = None
        self.queue.clear()
        self.queued_ids.clear()

    def pause(self) -> None:
        self._pause_depth += 1
        self.timer.stop()
        self.startup_timer.stop()

    def resume(self, check_now: bool = True) -> None:
        if self._pause_depth == 0:
            return
        self._pause_depth -= 1
        if self._pause_depth or not self._running:
            return
        self.timer.start()
        if check_now:
            QTimer.singleShot(0, self.check_now)

    def check_now(self) -> None:
        if self._pause_depth:
            return
        self._stopped = False
        for reminder in self.store.due_reminders():
            key = f"legacy:{int(reminder['id'])}"
            if key not in self.queued_ids:
                self.queue.append((key, reminder))
                self.queued_ids.add(key)
        for reminder in self.store.schedules.due_notifications():
            key = _schedule_key(reminder)
            if key not in self.queued_ids:
                self.queue.append((key, reminder))
                self.queued_ids.add(key)
        self._show_next()

    def _show_next(self) -> None:
        # _finished() queues this through a zero-delay timer that stop() cannot
        # cancel, so a service stopped in between must not query the store.
        if self._stopped:
            return
        if self.active_dialog is not None:
            return
        due = {f"legacy:{int(row['id'])}": row for row in self.store.due_reminders()}
        due.update({_schedule_key(row): row for row in self.store.schedules.due_notifications()})
        reminder = None
        reminder_key = ""
        while self.queue and reminder is None:
            queued_key, _queued = self.queue.popleft()
            reminder = due.get(queued_key)
            if reminder is None:
                self.queued_ids.discard(queued_key)
            else:
                reminder_key = queued_key
        if reminder is None:
            return
        is_schedule = reminder_key.startswith("schedule:")
        dialog = self._create_pet_alert(reminder, is_schedule)
        if dialog is None:
            dialog = ScheduleAlertDialog(reminder, self.parent()) if is_schedule else ReminderAlertDialog(reminder, self.parent())
            if is_schedule:
                dialog.completed.connect(self._complete_schedule)
                dialog.snoozed.connect(self._snooze_schedule)
                dialog.schedule_open_requested.connect(self.open_schedule_callback)
            else:
                dialog.completed.connect(self._complete)
                dialog.snoozed.connect(self._snooze)
                dialog.skipped.connect(self._skip)
            dialog.note_open_requested.connect(self.open_note_callback)
        elif is_schedule:
            occurrence_at = str(reminder["occurrence_at"])
            dialog.completed.connect(lambda notification_id: self._complete_schedule(notification_id, occurrence_at))
            dialog.snoozed.connect(lambda notification_id, minutes: self._snooze_schedule(notification_id, occurrence_at, minutes))
            dialog.note_open_requested.connect(self.open_note_callback)
            dialog.schedule_open_requested.connect(self.open_schedule_callback)
        else:
            dialog.completed.connect(self._complete)
            dialog.snoozed.connect(self._snooze)
            dialog.skipped.connect(self._skip)
            dialog.note_open_requested.connect(self.open_note_callback)
        self.active_dialog = dialog
        dialog.finished.connect(lambda _result, key=reminder_key: self._finished(key))
        dialog.show()

    def _create_pet_alert(self, reminder, is_schedule: bool):
        """Use the pet surface when available; retain the legacy dialog as fallback."""
        if not _setting_bool(self.store.setting("toma_pet_alert_enabled", "true"), True):
            return None
        try:
            persistent_pet = self.pet_controller.visible_window if self.pet_controller is not None else None
            return TomaPetAlertDialog(
                reminder, is_schedule, self.parent(),
                persistent_pet=persistent_pet,
                modifier=modifier_setting(self.store),
            )
        except (OSError, RuntimeError, ValueError):
            return None

    def _complete(self, reminder_id: int) -> None:
        self.store.complete_reminder(reminder_id)
        self.refresh_callback()

    def _snooze(self, reminder_id: int, minutes: int) -> None:
        self.store.snooze_reminder(reminder_id, minutes)
        self.refresh_callback()

    def _skip(self, reminder_id: int) -> None:
        self.store.skip_reminder(reminder_id)
        self.refresh_callback()

    def _complete_schedule(self, notification_id: int, occurrence_at: str) -> None:
        self.store.schedules.complete_notification(notification_id, occurrence_at)
        self.refresh_callback()

    def _snooze_schedule(self, notification_id: int, occurrence_at: str, minutes: int) -> None:
        self.store.schedules.snooze_notification(notification_id, occurrence_at, minutes)
        self.refresh_callback()

    def _finished(self, reminder_key) -> None:
        self.queued_ids.discard(reminder_key)
        self.active_dialog = None
        QTimer.singleShot(0, self._show_next)


def _schedule_key(reminder) -> str:
    return f"schedule:{reminder['notification_id']}:{reminder['occurrence_at']}"


def _setting_bool(value: str, default: bool) -> bool:
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default
