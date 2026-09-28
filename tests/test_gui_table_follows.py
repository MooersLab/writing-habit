"""The forms work on the table the grid holds.

A command reads a file, and the Schedule tab is where the writer decides which
file that is. Opening a table there, or saving it under a new name, fills the
table argument of every form that takes one, so the Sheets tab does not have to
be pointed at the same file by hand.

The grid owns the choice. A form reads it and never writes it back, so there is
one answer to which week is being worked on.
"""
from __future__ import annotations

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
def values(monkeypatch, tmp_path):
    store = {"db": "", "table_dir": "", "out_dir": "", "table": "",
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
    return store


@pytest.fixture
def window(qtbot, values):
    from writing_habit.gui.mainwindow import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.confirm_exit = lambda: True
    return win


def test_which_argument_names_a_table(values):
    """The rule is read off the parsers, not kept in a second list."""
    from writing_habit import cli
    from writing_habit.gui import argspec

    specs = argspec.commands(cli.build_parser())
    assert argspec.table_dest(specs["name"]) == "table"
    # plan import calls it path, and its help says it is the weekly org table
    assert argspec.table_dest(specs["plan import"]) == "path"
    # track import also calls it path, but that path is the actuals file
    assert argspec.table_dest(specs["track import"]) is None
    assert argspec.table_dest(specs["compare"]) is None


def test_the_scheduler_commands_all_name_a_table(values):
    """generate, export, sheets and check each take one."""
    pytest.importorskip("writing_schedule")
    from writing_schedule import cli as ws_cli

    from writing_habit.gui import argspec

    specs = argspec.commands(ws_cli.build_parser())
    for name in ("generate", "export", "sheets", "check"):
        assert argspec.table_dest(specs[name]) == "table", name


def test_opening_a_table_fills_the_sheets_form(window, tmp_path):
    """The complaint that started this: Sheets should show the same table."""
    path = tmp_path / "week.org"
    path.write_text(TABLE, encoding="utf-8")
    window.editor.open(str(path))

    sheets = window.panels.get("writing-schedule sheets")
    if sheets is None:
        pytest.skip("writing-schedule is not installed")
    assert sheets.values()["table"] == str(path)
    assert str(path) in sheets.command()


def test_every_form_that_takes_a_table_is_filled(window, tmp_path):
    """Not only Sheets, because they all read the same file."""
    path = tmp_path / "week.org"
    path.write_text(TABLE, encoding="utf-8")
    filled = window.use_table(str(path))
    assert filled >= 1

    from writing_habit.gui import argspec

    seen = set()
    for panel in window.panels.values():
        if id(panel) in seen:
            continue
        seen.add(id(panel))
        dest = argspec.table_dest(panel.spec)
        if dest is not None:
            assert panel.values()[dest] == str(path), panel.spec.name


def test_a_form_without_a_table_is_left_alone(window, tmp_path):
    """track import keeps pointing at the actuals file."""
    track = window.panels.get("track import")
    if track is None:
        pytest.skip("the track import form is not built")
    before = track.values().get("path")
    window.use_table(str(tmp_path / "week.org"))
    assert track.values().get("path") == before
    assert track.set_table(str(tmp_path / "week.org")) is False


def test_saving_under_a_new_name_moves_the_forms(window, tmp_path, monkeypatch):
    """Save as changes which file the commands will read."""
    first = tmp_path / "week.org"
    first.write_text(TABLE, encoding="utf-8")
    window.editor.open(str(first))

    second = tmp_path / "renamed.org"
    monkeypatch.setattr(
        "writing_habit.gui.schedule_editor.QtWidgets.QFileDialog.getSaveFileName",
        staticmethod(lambda *a, **k: (str(second), "")))
    window.editor.save_as()

    sheets = window.panels.get("writing-schedule sheets")
    if sheets is None:
        pytest.skip("writing-schedule is not installed")
    assert sheets.values()["table"] == str(second)


def test_a_new_form_starts_on_the_remembered_table(values, qtbot, tmp_path):
    """A form built later picks the table up from the stored setting."""
    pytest.importorskip("writing_schedule")
    from writing_schedule import cli as ws_cli

    from writing_habit.gui import argspec
    from writing_habit.gui.command_panel import CommandPanel

    path = tmp_path / "week.org"
    path.write_text(TABLE, encoding="utf-8")
    values["table"] = str(path)

    spec = argspec.commands(ws_cli.build_parser())["sheets"]
    panel = CommandPanel(spec, prog="writing-schedule")
    qtbot.addWidget(panel)
    panel.seed_from_settings()
    assert panel.values()["table"] == str(path)


def test_the_forms_do_not_write_the_setting_back(window, tmp_path, values):
    """Browsing in a form does not change which table reopens at startup."""
    path = tmp_path / "week.org"
    path.write_text(TABLE, encoding="utf-8")
    window.editor.open(str(path))
    assert values["table"] == str(path)

    sheets = window.panels.get("writing-schedule sheets")
    if sheets is None:
        pytest.skip("writing-schedule is not installed")
    sheets.fields["table"].set_value(str(tmp_path / "elsewhere.org"))
    sheets.remember()
    assert values["table"] == str(path)
