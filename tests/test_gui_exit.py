"""Leaving the window is one path, whichever way the writer starts it.

The window has three ways out: the Quit button at the right of the status bar,
File > Quit with its keyboard sequence, and the close box in the title bar. All
three go through ``closeEvent``, so the check for unfinished work and for an
unsaved weekly table cannot be bypassed by choosing a different route.
"""
from __future__ import annotations

import pytest

from writing_habit.gui.qt import QtGui, QtWidgets


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    """A window whose stored settings live in the test, not the user's account."""
    store = {"db": "", "table_dir": str(tmp_path), "out_dir": str(tmp_path),
             "timezone": "America/Chicago", "week": ""}
    for module in ("writing_habit.gui.settings",
                   "writing_habit.gui.command_panel.settings",
                   "writing_habit.gui.schedule_editor.settings"):
        monkeypatch.setattr(f"{module}.get", lambda key: store.get(key, ""))
        monkeypatch.setattr(f"{module}.put",
                            lambda key, value: store.__setitem__(key, value))
    saved = []
    monkeypatch.setattr("writing_habit.gui.settings.save_window",
                        lambda win: saved.append(win))
    monkeypatch.setattr("writing_habit.gui.settings.restore_window",
                        lambda win: False)

    from writing_habit.gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.saved_layout = saved
    return win


def test_the_status_bar_carries_a_quit_button(window):
    """The button is there, it says Quit, and it explains itself."""
    assert window.quit_button.text() == "Quit"
    assert window.quit_button.toolTip()
    # A permanent widget sits at the right end, where a status message on the
    # left never covers it.
    assert window.quit_button.parent() is window.statusBar()


def test_the_menu_action_carries_a_real_shortcut(window):
    """File > Quit binds a sequence on every platform."""
    assert not window.quit_action.shortcut().isEmpty()
    assert window.quit_action.menuRole() == QtWidgets.QAction.QuitRole


def test_a_quiet_window_closes(window):
    """With nothing running and nothing unsaved, the window goes."""
    assert window.confirm_exit() is True
    assert window.close() is True
    assert window.saved_layout == [window]


def test_the_button_closes_the_window(window, qtbot):
    """Pressing the button takes the same path as the close box."""
    window.show()
    window.quit_button.click()
    assert not window.isVisible()
    assert window.saved_layout == [window]


def test_an_unsaved_table_is_offered_for_saving(window, monkeypatch):
    """A dirty grid stops the exit until the writer answers."""
    class Table:
        dirty = True

    class Editor:
        table = Table()
        calls = 0

        def save(self):
            Editor.calls += 1
            return "/tmp/week.org"

    window.editor = Editor()
    assert window.unsaved_table() is True

    answers = iter([QtWidgets.QMessageBox.Cancel,
                    QtWidgets.QMessageBox.Save,
                    QtWidgets.QMessageBox.Discard])
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: next(answers)))

    try:
        assert window.confirm_exit() is False  # Cancel keeps the window
        assert Editor.calls == 0
        assert window.confirm_exit() is True   # Save writes, then leaves
        assert Editor.calls == 1
        assert window.confirm_exit() is True   # Discard leaves without writing
        assert Editor.calls == 1
    finally:
        # qtbot closes the window at teardown, which would ask again.
        window.editor = None


def test_a_dismissed_save_dialog_keeps_the_window(window, monkeypatch):
    """Save that returns nothing means the file dialog was dismissed."""
    class Table:
        dirty = True

    class Editor:
        table = Table()

        def save(self):
            return None

    window.editor = Editor()
    monkeypatch.setattr(QtWidgets.QMessageBox, "question",
                        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Save))
    try:
        assert window.confirm_exit() is False
    finally:
        window.editor = None


def test_a_running_command_is_named_once(window):
    """A panel reachable under two keys is reported under one name."""
    panel = next(iter(window.panels.values()))
    panel.worker = object()
    try:
        names = window.running_commands()
        assert len(names) == 1
        assert " " in names[0]          # the long "writing-habit compare" key
    finally:
        panel.worker = None
    assert window.running_commands() == []


def test_a_running_command_can_hold_the_exit(window, monkeypatch):
    """The warning defaults to waiting, and waiting keeps the window open."""
    panel = next(iter(window.panels.values()))
    panel.worker = object()

    pressed = {}

    def fake_exec(box):
        # The default button is what Return would press, so it is the answer
        # the writer gets by reflex.
        pressed["clicked"] = box.defaultButton()
        box.clickedButton = lambda: pressed["clicked"]
        return 0

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec_", fake_exec)
    try:
        assert window.confirm_exit() is False
        assert pressed["clicked"].text() == "Keep waiting"
    finally:
        panel.worker = None


def test_the_close_event_is_refused_when_work_is_open(window, monkeypatch):
    """An ignored close leaves the window up and writes no layout."""
    monkeypatch.setattr(window, "confirm_exit", lambda: False)
    window.show()
    assert window.close() is False
    assert window.isVisible()
    assert window.saved_layout == []
