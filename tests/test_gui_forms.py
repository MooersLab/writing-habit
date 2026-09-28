"""The generated forms, the command preview, and the runner.

The window is built offscreen. Every test that needs Qt is skipped when the
graphical extra is absent, so the suite still passes on a checkout installed
without it.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit import cli                                  # noqa: E402
from writing_habit.gui import argspec, forms, runner           # noqa: E402
from writing_habit.gui.command_panel import CommandPanel       # noqa: E402
from writing_habit.gui.qt import QtWidgets                     # noqa: E402

SPECS = argspec.commands(cli.build_parser())
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def blank_settings(monkeypatch):
    """Keep the tests away from the real preferences of the person running them."""
    store = {}
    monkeypatch.setattr("writing_habit.gui.settings.get", lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr("writing_habit.gui.command_panel.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.command_panel.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    return store


@pytest.mark.parametrize("name", sorted(SPECS))
def test_every_command_builds_a_field_for_every_option(app, blank_settings, name):
    panel = CommandPanel(SPECS[name])
    assert set(panel.fields) == {opt.dest for opt in SPECS[name].options}


def test_the_widget_rule_reads_the_flag_not_the_dest(app, blank_settings):
    """--from is a date and --start is a clock time, though both mean ``start``."""
    history = CommandPanel(SPECS["history"])
    add = CommandPanel(SPECS["track add"])
    assert isinstance(history.fields["start"], forms.DateField)
    assert isinstance(add.fields["start"], forms.TimeField)


def test_the_widget_rule_covers_the_other_shapes(app, blank_settings):
    add = CommandPanel(SPECS["track add"])
    assert isinstance(add.fields["minutes"], forms.IntField)
    assert isinstance(add.fields["note"], forms.TextField)
    assert isinstance(add.fields["db"], forms.PathField)
    # the parser declares no choices for --category, so the box suggests
    assert isinstance(add.fields["category"], forms.SuggestionField)
    assert isinstance(CommandPanel(SPECS["context set"]).fields["tag"],
                      forms.SuggestionField)

    imported = CommandPanel(SPECS["track import"])
    assert isinstance(imported.fields["format"], forms.ChoiceField)
    assert isinstance(imported.fields["path"], forms.PathField)


def test_the_preview_is_the_command_that_will_run(app, blank_settings):
    panel = CommandPanel(SPECS["compare"])
    panel.fields["week"].set_value("2026-01-19")
    panel.fields["db"].set_value("habit.db")
    panel.refresh()
    assert panel.preview.text() == "writing-habit compare --week 2026-01-19 --db habit.db"
    # and it parses, which is the property that keeps the preview honest
    parsed = cli.build_parser().parse_args(panel.argv())
    assert parsed.command == "compare" and parsed.week == "2026-01-19"


def test_an_optional_date_is_omitted_until_it_is_sent(app, blank_settings):
    panel = CommandPanel(SPECS["history"])
    panel.fields["db"].set_value("habit.db")
    panel.refresh()
    assert panel.preview.text() == "writing-habit history --db habit.db"
    panel.fields["start"].set_value("2026-01-05")
    panel.refresh()
    assert "--from 2026-01-05" in panel.preview.text()


def test_run_is_blocked_until_the_required_values_are_present(app, blank_settings):
    panel = CommandPanel(SPECS["plan import"])
    panel.fields["db"].set_value("")
    panel.fields["path"].set_value("")
    panel.refresh()
    assert not panel.run_button.isEnabled()
    assert "path" in panel.note.text()

    panel.fields["path"].set_value("examples/my-week.org")
    panel.fields["db"].set_value("habit.db")
    panel.refresh()
    assert panel.run_button.isEnabled()
    assert panel.note.text() == ""


def test_the_runner_executes_the_real_command(tmp_path):
    """initdb through the runner creates a usable database."""
    dbpath = tmp_path / "habit.db"
    output, code = runner.run_sync(["initdb", "--db", str(dbpath)])
    assert code == 0
    assert f"Initialized {dbpath}" in output
    assert dbpath.exists()

    from writing_habit import db
    con = db.connect(str(dbpath))
    try:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    assert {"plan_block", "session", "project"} <= names


def test_the_runner_reports_a_bad_argument_without_exiting(tmp_path):
    """argparse raises SystemExit, which a windowed program must not honor."""
    output, code = runner.run_sync(["compare", "--db", str(tmp_path / "x.db")])
    assert code == 2
    assert "week" in output


def test_a_string_exit_becomes_a_message_and_a_failing_code(monkeypatch):
    """sys.exit("message") means failure, and the message must reach the user.

    plan import uses that form to explain a missing writing-schedule package.
    """
    def boom(argv):
        raise SystemExit("plan import needs the writing-schedule package")

    monkeypatch.setattr("writing_habit.cli.main", boom)
    output, code = runner.run_sync(["plan", "import", "x.org"])
    assert code == 1
    assert "needs the writing-schedule package" in output


def test_a_successful_run_is_remembered(app, blank_settings, tmp_path):
    panel = CommandPanel(SPECS["initdb"])
    panel.fields["db"].set_value(str(tmp_path / "habit.db"))
    panel.refresh()
    output, code = runner.run_sync(panel.argv())
    assert code == 0
    panel.remember()
    assert blank_settings["db"] == str(tmp_path / "habit.db")


def test_the_panel_logs_the_shell_command(app, blank_settings, tmp_path):
    panel = CommandPanel(SPECS["initdb"])
    panel.fields["db"].set_value(str(tmp_path / "habit.db"))
    panel.refresh()
    lines = []
    panel.logged.connect(lines.append)
    panel.run()
    panel.worker.wait(5000)
    app.processEvents()
    assert lines[0].startswith("$ writing-habit initdb --db ")
    assert any("Initialized" in line for line in lines)
