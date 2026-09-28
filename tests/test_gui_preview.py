"""The preview of what a command wrote.

Two seams are covered here. A command panel must know which files its run
produced, both from the form and from the lines the command printed, and the
view must render the three kinds of output the tools write.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit import cli                                    # noqa: E402
from writing_habit.gui import argspec, runner                    # noqa: E402
from writing_habit.gui.command_panel import CommandPanel         # noqa: E402
from writing_habit.gui.qt import QtWidgets                       # noqa: E402
from writing_habit.gui.report_view import ArtifactView, PreviewDock  # noqa: E402

SPECS = argspec.commands(cli.build_parser())
ROOT = Path(__file__).resolve().parents[1]
XPORT_DB = ROOT / "tests" / "fixtures" / "cross-port.db"
WEEK = "2026-01-19"


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def blank_settings(monkeypatch):
    store = {}
    monkeypatch.setattr("writing_habit.gui.command_panel.settings.get",
                        lambda key: store.get(key, ""))
    monkeypatch.setattr("writing_habit.gui.command_panel.settings.put",
                        lambda key, value: store.__setitem__(key, value))
    return store


@pytest.fixture()
def view(app):
    """A view that ignores the web engine, which is the fallback path."""
    return ArtifactView(prefer_web_engine=False)


def _png(path: Path, width: int = 40, height: int = 30) -> Path:
    from writing_habit.gui.qt import QtGui

    image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("white"))
    image.save(str(path))
    return path


# -- what the view shows ---------------------------------------------------

def test_it_starts_with_nothing_to_show(view):
    assert not view.open_button.isEnabled()
    assert "Nothing written" in view.name_label.text()


def test_it_renders_a_dashboard(view, tmp_path):
    from writing_habit import db
    from writing_habit.dashboard import write_dashboard

    out = tmp_path / "week.html"
    con = db.connect(str(XPORT_DB))
    try:
        write_dashboard(con, WEEK, str(out))
    finally:
        con.close()

    assert view.show_file(out) is True
    assert view.stack.currentWidget() is view.text
    assert "Writing dashboard" in view.text.toPlainText()
    assert view.open_button.isEnabled()
    # the fallback says plainly what it cannot render
    assert "rich-text widget" in view.footer.text()


def test_it_renders_a_plot(view, tmp_path):
    path = _png(tmp_path / "trend.png", 64, 48)
    assert view.show_file(path) is True
    assert view.stack.currentWidget() is view.image_area
    assert not view.image_label.pixmap().isNull()
    assert "64 by 48" in view.footer.text()


def test_it_shows_an_org_file_as_text(view, tmp_path):
    path = tmp_path / "sheet.org"
    path.write_text("#+TITLE: a sheet\n| a | b |\n", encoding="utf-8")
    assert view.show_file(path) is True
    assert "#+TITLE: a sheet" in view.text.toPlainText()


def test_it_names_a_pdf_rather_than_pretending(view, tmp_path):
    path = tmp_path / "sheets.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    assert view.show_file(path) is False
    assert "cannot be shown here" in view.note.text()
    assert view.open_button.isEnabled()          # but it can still be opened


def test_a_file_that_vanished_says_so(view, tmp_path):
    path = tmp_path / "gone.html"
    assert view.show_file(path) is False
    assert "not there any more" in view.note.text()
    assert not view.open_button.isEnabled()


def test_a_very_long_text_file_is_not_loaded(view, tmp_path):
    path = tmp_path / "big.org"
    path.write_text("x" * 300_000, encoding="utf-8")
    assert view.show_file(path) is False
    assert "too long to show" in view.note.text()


def test_a_broken_image_is_reported(view, tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"not an image")
    assert view.show_file(path) is False
    assert "not an image" in view.note.text()


# -- the dock of several outputs -------------------------------------------

def test_the_dock_opens_a_tab_per_file(app, tmp_path):
    dock = PreviewDock()
    first = _png(tmp_path / "one.png")
    second = tmp_path / "two.org"
    second.write_text("| a |\n", encoding="utf-8")

    dock.show_files([str(first), str(second)])
    assert dock.tabs.count() == 2
    assert [dock.tabs.tabText(i) for i in range(2)] == ["one.png", "two.org"]


def test_the_dock_reuses_the_tab_of_a_file_it_already_shows(app, tmp_path):
    dock = PreviewDock()
    path = _png(tmp_path / "trend.png")
    dock.show_one(str(path))
    dock.show_one(str(path))
    assert dock.tabs.count() == 1


def test_the_dock_keeps_only_the_recent_files(app, tmp_path):
    dock = PreviewDock(limit=3)
    for index in range(5):
        dock.show_one(str(_png(tmp_path / f"p{index}.png")))
    assert dock.tabs.count() == 3
    assert dock.tabs.tabText(dock.tabs.count() - 1) == "p4.png"


# -- what a panel says it wrote --------------------------------------------

def test_a_panel_reports_the_file_it_was_told_to_write(app, blank_settings, tmp_path):
    import shutil

    dbpath = tmp_path / "habit.db"
    shutil.copy(XPORT_DB, dbpath)
    out = tmp_path / "week.html"

    panel = CommandPanel(SPECS["dashboard"])
    panel.fields["week"].set_value(WEEK)
    panel.fields["out"].set_value(str(out))
    panel.fields["db"].set_value(str(dbpath))
    panel.refresh()

    produced = []
    panel.produced.connect(produced.append)
    panel.run()
    panel.worker.wait(10_000)
    app.processEvents()

    assert produced == [[str(out)]]
    assert out.exists()


def test_a_panel_reads_the_paths_out_of_the_output(tmp_path):
    written = tmp_path / "sheets-week-2026-01-19.pdf"
    written.write_bytes(b"%PDF-1.4\n")
    other = tmp_path / "week.ics"
    other.write_text("BEGIN:VCALENDAR\n", encoding="utf-8")
    output = (f"Wrote {written}\n"
              f"Wrote iCalendar: {other}\n"
              f"Wrote plot to {tmp_path / 'missing.png'}\n"
              "Wrote nothing at all\n")
    found = CommandPanel.paths_in_output(output)
    assert found == [str(written), str(other)]   # the missing file is left out


def test_a_failed_run_reports_no_files(app, blank_settings, tmp_path):
    panel = CommandPanel(SPECS["dashboard"])
    panel.fields["week"].set_value(WEEK)
    panel.fields["out"].set_value(str(tmp_path / "never.html"))
    panel.fields["db"].set_value(str(tmp_path / "absent.db"))
    panel.refresh()

    produced = []
    panel.produced.connect(produced.append)
    panel.run()
    panel.worker.wait(10_000)
    app.processEvents()
    assert produced == []


# -- the optional web engine ----------------------------------------------
#
# Qt refuses to import the web engine once a QApplication exists, so the
# interface probes for it at startup and caches the answer. Getting that order
# wrong costs nothing visible: the preview simply falls back to rich text
# forever, on a machine where the faithful renderer is installed.

def test_the_startup_step_runs_before_the_application_is_built():
    """app.main prepares the engine before it constructs the QApplication."""
    import inspect

    from writing_habit.gui import app as app_module

    source = inspect.getsource(app_module.main)
    assert "prepare_for_web_engine()" in source
    assert source.index("prepare_for_web_engine()") < source.index("QApplication(")


def test_the_probe_is_cached_so_a_late_call_still_answers(app, monkeypatch):
    from writing_habit.gui import qt

    monkeypatch.setattr(qt, "_WEB_ENGINE", None)
    assert qt.web_engine_view() is None                  # a cached miss stays a miss

    sentinel = object()
    monkeypatch.setattr(qt, "_WEB_ENGINE", sentinel)
    assert qt.web_engine_view() is sentinel              # and a cached hit stays a hit


def test_the_view_follows_the_probe(app, monkeypatch, tmp_path):
    """With no engine the view renders text; with one it uses the engine."""
    monkeypatch.setattr("writing_habit.gui.report_view.web_engine_view",
                        lambda: None)
    plain = ArtifactView()
    assert plain.use_web_engine is False
    assert plain.web is None

    page = tmp_path / "page.html"
    page.write_text("<h1>a week</h1>", encoding="utf-8")
    assert plain.show_file(page) is True
    assert plain.stack.currentWidget() is plain.text
