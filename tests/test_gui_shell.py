"""Tests for the graphical shell of build step 1.

The suite runs headless. The Makefile exports ``QT_QPA_PLATFORM=offscreen``,
and the fixture below sets it as well so a bare ``pytest`` run behaves the same.
Every test that needs Qt is skipped when the graphical extra is absent, so the
suite still passes on a checkout installed without it.
"""

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="the graphical extra is not installed")

from writing_habit.gui import mainwindow                    # noqa: E402
from writing_habit.gui import qt                            # noqa: E402


@pytest.fixture(scope="module")
def app():
    """One QApplication for the module, which is all Qt allows."""
    existing = qt.QtWidgets.QApplication.instance()
    yield existing or qt.QtWidgets.QApplication([])


@pytest.fixture()
def window(app, tmp_path, monkeypatch):
    """A window whose settings are read from a scratch location."""
    monkeypatch.setattr(mainwindow.settings, "get", lambda key: "")
    win = mainwindow.MainWindow()
    yield win
    win.close()


def test_every_loop_stage_has_a_tab(window):
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert titles == [entry[0] for entry in mainwindow.TABS]
    assert titles[0] == "Schedule"          # the loop starts at the table


def test_window_carries_the_version(window):
    from writing_habit import __version__
    assert __version__ in window.windowTitle()


def test_status_bar_reports_no_database_yet(window):
    assert "No database" in window.statusBar().currentMessage()


def test_session_log_starts_empty_and_accepts_lines(window):
    assert window.log.toPlainText() == ""
    window.append_log("writing-habit compare --week 2026-01-19 --db habit.db")
    assert "compare --week 2026-01-19" in window.log.toPlainText()


def test_the_log_dock_can_be_toggled_from_the_view_menu(window):
    actions = [a.text() for menu in window.menuBar().actions()
               for a in (menu.menu().actions() if menu.menu() else [])]
    assert any("Session log" in text for text in actions)


def test_about_text_states_the_split_license():
    from writing_habit import __version__
    text = mainwindow.ABOUT.format(version=__version__, binding=qt.versions())
    assert "MIT" in text and "GPL" in text


def test_qt_module_reports_its_binding():
    assert qt.BINDING == "PyQt5"
    assert "PyQt5" in qt.versions()
