"""The Generate and Sheets tabs, which drive the optional writing-schedule package.

The same machinery that generated the tracker forms reads the scheduler parser,
so these tests check the seam rather than the widgets again. Two facts matter.
A panel must run the program its command belongs to, and a missing scheduler
must produce an explanation rather than a disappearing tab.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit.gui import mainwindow, runner                # noqa: E402
from writing_habit.gui.qt import QtWidgets                      # noqa: E402

HAS_SCHEDULE = runner.available("writing-schedule")
needs_schedule = pytest.mark.skipif(
    not HAS_SCHEDULE, reason="the writing-schedule package is not installed")


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def blank_settings(monkeypatch):
    store = {}
    for module in ("writing_habit.gui.settings", "writing_habit.gui.command_panel"):
        monkeypatch.setattr(f"{module}.settings.get" if module.endswith("panel")
                            else f"{module}.get", lambda key: store.get(key, ""))
        monkeypatch.setattr(f"{module}.settings.put" if module.endswith("panel")
                            else f"{module}.put",
                            lambda key, value: store.__setitem__(key, value))
    return store


def test_the_program_table_names_both_command_lines():
    assert set(runner.PROGRAMS) == {"writing-habit", "writing-schedule"}
    assert runner.available("writing-habit")


def test_an_unknown_program_is_reported_rather_than_raised():
    output, code = runner.run_sync(["generate"], prog="writing-nothing")
    assert code == 1 and "cannot run writing-nothing" in output


@needs_schedule
def test_the_scheduler_tabs_carry_generated_panels(app, blank_settings):
    window = mainwindow.MainWindow()
    try:
        for name in ("generate", "export", "sheets", "template", "check", "weeks"):
            key = f"writing-schedule {name}"
            assert key in window.panels, f"no panel for {key}"
            assert window.panels[key].prog == "writing-schedule"
    finally:
        window.close()


@needs_schedule
def test_a_scheduler_preview_names_the_scheduler(app, blank_settings):
    window = mainwindow.MainWindow()
    try:
        panel = window.panels["writing-schedule sheets"]
        panel.fields["table"].set_value("examples/my-week.org")
        panel.fields["week"].set_value("2026-01-19")
        panel.fields["dir"].set_value("out")
        panel.refresh()
        assert panel.preview.text().startswith("writing-schedule sheets ")
        assert "--engine reportlab" in panel.preview.text()
        # the preview parses, which is what keeps it honest
        from writing_schedule import cli as ws_cli
        parsed = ws_cli.build_parser().parse_args(panel.argv())
        assert parsed.command == "sheets" and parsed.format == "pdf"
    finally:
        window.close()


@needs_schedule
def test_the_runner_reaches_the_second_program(tmp_path):
    out, code = runner.run_sync(
        ["template", "3", "--out", str(tmp_path / "blank.org")],
        prog="writing-schedule")
    assert code == 0
    text = (tmp_path / "blank.org").read_text(encoding="utf-8")
    assert "| Time <l> |" in text and "| A: |" in text


@needs_schedule
def test_check_reports_a_clash_with_its_own_exit_code(tmp_path):
    table = tmp_path / "clash.org"
    table.write_text(
        "| Time <l>    | M |\n"
        "|-------------+---|\n"
        "| Generative: |   |\n"
        "| 04:00-05:30 | A |\n"
        "| Rewriting:  |   |\n"
        "| 05:00-06:30 | B |\n",
        encoding="utf-8")
    out, code = runner.run_sync(["check", str(table)], prog="writing-schedule")
    assert code == 3                      # the documented clash exit code
    assert "overlaps" in out


def test_a_missing_scheduler_explains_itself(app, blank_settings, monkeypatch):
    monkeypatch.setattr(runner, "available", lambda prog: prog == "writing-habit")
    window = mainwindow.MainWindow()
    try:
        titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        page = window.tabs.widget(titles.index("Generate"))
        labels = page.findChildren(QtWidgets.QLabel)
        assert any("writing-schedule" in label.text() for label in labels)
        assert any("pip install" in label.text() for label in labels)
        assert "writing-schedule not installed" in window.statusBar().currentMessage()
    finally:
        window.close()
