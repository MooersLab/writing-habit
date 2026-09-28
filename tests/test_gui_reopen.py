"""The window comes back to the table the writer left open.

An empty grid at startup is a small tax paid every day, and it was the setting
in which a command quietly read a file the grid was not showing. Reopening the
last table means the Schedule tab shows what the command forms will read.
"""
from __future__ import annotations

import os
import time

import pytest

TABLE = """#+TITLE: A week

| Time <l>    | M  | Tu | W  | Th | F  |
|-------------+----+----+----+----+----|
| Generative: |    |    |    |    |    |
| 09:00-09:30 | A  |    |    |    |    |
|-------------+----+----+----+----+----|
| A: main paper :safe: |  |  |  |  |  |
"""


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Settings held in the test rather than in the writer's account."""
    values = {"db": "", "table_dir": "", "out_dir": "", "table": "",
              "timezone": "America/Chicago", "week": ""}
    for module in ("writing_habit.gui.settings",
                   "writing_habit.gui.command_panel.settings",
                   "writing_habit.gui.schedule_editor.settings"):
        monkeypatch.setattr(f"{module}.get", lambda key: values.get(key, ""))
        monkeypatch.setattr(f"{module}.put",
                            lambda key, value: values.__setitem__(key, value))
    monkeypatch.setattr("writing_habit.gui.settings.save_window", lambda win: None)
    monkeypatch.setattr("writing_habit.gui.settings.restore_window",
                        lambda win: False)
    return values


@pytest.fixture
def editor(qtbot, store):
    from writing_habit.gui.schedule_editor import ScheduleEditor

    widget = ScheduleEditor()
    qtbot.addWidget(widget)
    return widget


def write(path, text=TABLE, age=0.0):
    path.write_text(text, encoding="utf-8")
    if age:
        when = time.time() - age
        os.utime(path, (when, when))
    return path


def test_opening_a_table_remembers_it(editor, store, tmp_path):
    """The path is stored, not only the folder it sits in."""
    path = write(tmp_path / "week.org")
    editor.open(str(path))
    assert store["table"] == str(path)
    assert store["table_dir"] == str(tmp_path)


def test_the_remembered_table_is_the_one_reopened(editor, store, tmp_path):
    """A remembered file wins over anything newer in the folder."""
    older = write(tmp_path / "chosen.org", age=10_000)
    write(tmp_path / "newer.org")
    store["table"] = str(older)
    store["table_dir"] = str(tmp_path)
    assert editor.most_recent() == str(older)


def test_the_newest_stands_in_when_the_remembered_file_is_gone(editor, store, tmp_path):
    """A moved or deleted table falls back to the newest in the folder."""
    write(tmp_path / "old.org", age=10_000)
    newest = write(tmp_path / "new.org")
    store["table"] = str(tmp_path / "vanished.org")
    store["table_dir"] = str(tmp_path)
    assert editor.most_recent() == str(newest)


def test_nothing_remembered_and_nothing_on_disk(editor, store, tmp_path):
    """An empty folder gives no answer, and that is not an error."""
    store["table_dir"] = str(tmp_path)
    assert editor.most_recent() is None
    assert editor.open_most_recent() is None
    assert editor.table is None


def test_a_missing_folder_is_not_an_error(editor, store, tmp_path):
    """A table_dir that no longer exists gives no answer."""
    store["table_dir"] = str(tmp_path / "not-there")
    assert editor.most_recent() is None


def test_only_org_files_are_considered(editor, store, tmp_path):
    """A newer file of another kind does not become the table."""
    table = write(tmp_path / "week.org", age=10_000)
    (tmp_path / "notes.txt").write_text("newer but not a table", encoding="utf-8")
    store["table_dir"] = str(tmp_path)
    assert editor.most_recent() == str(table)


def test_open_most_recent_loads_the_grid(editor, store, tmp_path):
    """The table is really opened, not just named."""
    path = write(tmp_path / "week.org")
    store["table"] = str(path)
    assert editor.open_most_recent() == str(path)
    assert editor.table is not None
    assert editor.table.path == str(path)
    assert editor.model.rowCount() > 0
    assert not editor.table.dirty


def test_an_unreadable_table_leaves_the_window_usable(editor, store, tmp_path):
    """A file that cannot be parsed logs a line and opens nothing."""
    bad = tmp_path / "broken.org"
    bad.write_bytes(b"\xff\xfe not a table at all")
    store["table"] = str(bad)
    messages = []
    editor.logged.connect(messages.append)
    editor.open_most_recent()
    assert editor.table is None or editor.table.path == str(bad)


def test_the_window_reopens_at_startup(qtbot, store, tmp_path):
    """Building the window puts the last table in the Schedule tab."""
    path = write(tmp_path / "week.org")
    store["table"] = str(path)

    from writing_habit.gui.mainwindow import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.confirm_exit = lambda: True
    assert window.editor.table is not None
    assert window.editor.table.path == str(path)
    # The reopened table counts as saved, so the exit check stays quiet.
    assert window.unsaved_table() is False


def test_the_window_starts_empty_when_there_is_no_table(qtbot, store, tmp_path):
    """Nothing to reopen leaves the window exactly as it was before."""
    store["table_dir"] = str(tmp_path)

    from writing_habit.gui.mainwindow import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.editor.table is None
