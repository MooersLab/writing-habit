"""A command must not read a file the grid has not written yet.

The grid holds an edit until Save, while a command reads the file on disk.
Running before saving therefore uses the old version, the generated schedule
comes out without the blocks that are visible on the screen, and nothing says
why. The run now stops and offers to save first.
"""
from __future__ import annotations

import pytest

from writing_habit.gui.qt import QtWidgets

TABLE = """#+TITLE: A week

| Time <l>    | M  | Tu | W  | Th | F  |
|-------------+----+----+----+----+----|
| Generative: |    |    |    |    |    |
| 09:00-09:30 |    |    |    |    |    |
|-------------+----+----+----+----+----|
| A: main paper :safe: |  |  |  |  |  |
"""


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    store = {"db": "", "table_dir": str(tmp_path), "out_dir": str(tmp_path),
             "timezone": "America/Chicago", "week": ""}
    for module in ("writing_habit.gui.settings",
                   "writing_habit.gui.command_panel.settings",
                   "writing_habit.gui.schedule_editor.settings"):
        monkeypatch.setattr(f"{module}.get", lambda key: store.get(key, ""))
        monkeypatch.setattr(f"{module}.put",
                            lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr("writing_habit.gui.settings.save_window", lambda win: None)
    monkeypatch.setattr("writing_habit.gui.settings.restore_window",
                        lambda win: False)

    from writing_habit.gui.mainwindow import MainWindow

    path = tmp_path / "week.org"
    path.write_text(TABLE, encoding="utf-8")
    win = MainWindow()
    qtbot.addWidget(win)
    win.editor.open(str(path))
    win.table_path = path
    # These tests deliberately leave the grid dirty. The exit check belongs to
    # test_gui_exit.py, and letting it run here would put a real modal dialog
    # in front of qtbot when it closes the window at the end of the test.
    win.confirm_exit = lambda: True
    return win


def dirty(window):
    """Type a code into the grid without saving."""
    index = window.editor.model.index(window.editor.model.rowCount() - 1, 1)
    window.editor.model.setData(index, "A")
    assert window.editor.table.dirty


def test_a_clean_table_never_asks(window):
    """Nothing was edited, so the run goes straight through."""
    assert window.confirm_disk_is_current([str(window.table_path)]) is True


def test_a_command_that_reads_another_file_never_asks(window, tmp_path):
    """The grid is dirty, but this command does not touch that file."""
    dirty(window)
    assert window.confirm_disk_is_current([str(tmp_path / "other.org")]) is True


def test_an_unsaved_scaffold_never_asks(window):
    """A table with no path cannot be the file the command names."""
    window.editor.scaffold(2)
    assert window.editor.table.path is None or window.editor.table.path == ""
    assert window.confirm_disk_is_current(["anything.org"]) is True


def _answer(monkeypatch, label):
    """Make the warning box answer with the button carrying ``label``."""
    seen = {}

    def fake_exec(box):
        for button in box.buttons():
            if box.buttonRole(button) != QtWidgets.QMessageBox.RejectRole and \
                    button.text().replace("&", "") == label:
                seen["clicked"] = button
        if "clicked" not in seen:
            seen["clicked"] = box.button(QtWidgets.QMessageBox.Cancel)
        box.clickedButton = lambda: seen["clicked"]
        return 0

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec_", fake_exec)
    return seen


def test_save_and_run_writes_the_file_first(window, monkeypatch):
    """The default answer saves, so the command reads what is on the screen."""
    dirty(window)
    _answer(monkeypatch, "Save and run")
    assert window.confirm_disk_is_current([str(window.table_path)]) is True
    assert not window.editor.table.dirty
    assert "| A" in window.table_path.read_text(encoding="utf-8")


def test_run_on_the_saved_version_leaves_the_file_alone(window, monkeypatch):
    """The writer can still run against what is on disk, knowingly."""
    dirty(window)
    _answer(monkeypatch, "Run on the saved version")
    before = window.table_path.read_text(encoding="utf-8")
    assert window.confirm_disk_is_current([str(window.table_path)]) is True
    assert window.editor.table.dirty
    assert window.table_path.read_text(encoding="utf-8") == before


def test_cancel_stops_the_run(window, monkeypatch):
    """Anything else keeps the command from starting."""
    dirty(window)
    _answer(monkeypatch, "no such button")
    assert window.confirm_disk_is_current([str(window.table_path)]) is False


def test_a_dismissed_save_dialog_stops_the_run(window, monkeypatch):
    """Save that writes nothing must not be treated as a save."""
    dirty(window)
    _answer(monkeypatch, "Save and run")
    monkeypatch.setattr(window.editor, "save", lambda: None)
    assert window.confirm_disk_is_current([str(window.table_path)]) is False


def test_every_panel_carries_the_guard(window):
    """The check is wired to the forms, not just available on the window."""
    assert window.panels
    for panel in window.panels.values():
        assert panel.guard == window.confirm_disk_is_current


def test_the_guard_can_stop_a_run(window, monkeypatch):
    """A refused guard means no worker is started."""
    panel = next(iter(window.panels.values()))
    panel.guard = lambda argv: False
    panel.run()
    assert panel.worker is None
