"""The Track tab's sync form and the File menu actions that drive it."""

from __future__ import annotations

import os
import sqlite3

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit import db                                # noqa: E402
from writing_habit.gui import forms, mainwindow, settings   # noqa: E402
from writing_habit.gui import qt                            # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = qt.QtWidgets.QApplication.instance()
    yield existing or qt.QtWidgets.QApplication([])


@pytest.fixture()
def store(monkeypatch):
    values = {}
    monkeypatch.setattr(settings, "get",
                        lambda key: values.get(key, settings.DEFAULTS[key]))
    monkeypatch.setattr(settings, "put", lambda key, value: values.__setitem__(key, value))
    return values


@pytest.fixture()
def paths(tmp_path):
    table = tmp_path / "Oct5.org"
    table.write_text("| Time | M |\n|------+---|\n| Z: 1008ToolsForQCrOfRNA :safe: | |\n",
                     encoding="utf-8")
    source = tmp_path / "mytime.db"
    con = sqlite3.connect(source)
    con.execute('CREATE TABLE zTimeSpent (id INTEGER PRIMARY KEY, DateDashed DATE,'
                ' Start TIME, "End" TIME, ProjectID INT, ProjectDirectory TEXT,'
                ' Description TEXT, Activity TEXT)')
    con.execute("INSERT INTO zTimeSpent VALUES (1, '2026-10-05', '05:30', '07:00',"
                " 1008, '1008ToolsForQCrOfRNA', 'grant', 'g')")
    con.commit()
    con.close()
    habit = tmp_path / "habit.db"
    c = db.connect(str(habit))
    db.init_db(c)
    c.execute("INSERT INTO plan_week(week_start, table_path) VALUES ('2026-10-05', ?)",
              (str(table),))
    c.commit()
    c.close()
    return str(source), str(habit)


def _window(app):
    return mainwindow.MainWindow()


def test_track_tab_offers_sync_first(app, store):
    track = next(t for t in mainwindow.TABS if t[0] == "Track")
    assert track[2][0] == ("writing-habit", "track sync")
    win = _window(app)
    panel = win.panels["track sync"]
    field = panel.fields["source"]
    assert isinstance(field, forms.PathField) and "*.db" in field.filter
    assert isinstance(panel.fields["since"], forms.DateField)
    win.close()


def test_sync_runs_from_remembered_paths_and_remembers_them(app, store, paths, qtbot):
    source, habit = paths
    store.update({"db": habit, "mytime_db": source})
    win = _window(app)
    assert win.sync_mytime() is True
    panel = win.panels["track sync"]
    qtbot.waitUntil(lambda: panel.worker is None, timeout=10000)
    assert "inserted 1" in panel.output.toPlainText()
    con = sqlite3.connect(habit)
    assert con.execute("SELECT actual_min FROM session").fetchone()[0] == 90
    con.close()
    assert store["mytime_db"] == source
    win.close()


def test_sync_without_a_source_says_what_is_missing(app, store):
    win = _window(app)
    assert win.sync_mytime() is False
    assert "source" in win.log.toPlainText()
    assert win.tabs.tabText(win.tabs.currentIndex()) == "Track"
    win.close()


def test_startup_sync_is_a_remembered_menu_choice(app, store, paths, qtbot):
    win = _window(app)
    assert not win.sync_on_start_action.isChecked()
    win.sync_on_start_action.setChecked(True)
    assert store["sync_on_start"] == "true"
    win.close()

    source, habit = paths
    store.update({"db": habit, "mytime_db": source})
    win = _window(app)
    panel = win.panels["track sync"]
    qtbot.waitUntil(lambda: "inserted 1" in panel.output.toPlainText(), timeout=10000)
    qtbot.waitUntil(lambda: panel.worker is None, timeout=10000)
    win.close()
