"""Teardown helpers shared by the Qt widget tests.

Two failure modes made the suite unreliable when tests ran together:

* Closing a window whose editor form had been touched popped the
  "저장하지 않은 변경 내용" modal, which never returns without a person to
  answer it, so the run hung.
* Closing the store while the widget was still alive let a later layout pass
  query a closed database.  PyQt6 turns an unhandled exception inside a Qt
  event handler into a hard process abort, which killed the remaining tests in
  the file without reporting them.

Both are avoided by retiring the widget completely before the store closes.
"""

from PyQt6.QtCore import QEvent


def destroy_widget(widget, app) -> None:
    """Close a widget and let Qt actually delete it before the store goes away."""
    if widget is None:
        return
    widget.hide()
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def accept_form_state(window) -> None:
    """Treat the current editor values as saved.

    ``new_action``/``load_selected``/``closeEvent`` all ask about unsaved changes
    first, and that prompt blocks forever without a person to answer it.  Tests
    that only care about what happens *after* the transition call this to move
    on without the question.
    """
    if window is not None and hasattr(window, "_set_action_form_baseline"):
        window._set_action_form_baseline()


def close_main_window(window, app) -> None:
    """Retire a MainWindow without tripping the unsaved-changes prompt."""
    if window is None:
        return
    accept_form_state(window)
    window.close()
    destroy_widget(window, app)


def close_alert_panel(panel, app) -> None:
    """Retire an AlertNotesPanel and its timers before its store closes."""
    if panel is None:
        return
    panel.shutdown()
    panel.close()
    destroy_widget(panel, app)
