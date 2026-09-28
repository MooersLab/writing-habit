"""The Documentation and README buttons open web pages in the default browser.

The launcher is replaced in every test, so the suite never opens a browser.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from writing_habit.gui import links

ROOT = Path(__file__).resolve().parents[1]


# -- the addresses -------------------------------------------------------------
def test_the_readme_address_points_at_the_repository_readme():
    assert links.README_URL == "https://github.com/MooersLab/writing-habit/blob/main/README.md"


def test_the_docs_address_names_a_page_in_this_checkout():
    """Until Read the Docs is published, the button opens docs/gui.md on GitHub."""
    prefix = f"{links.REPOSITORY}/blob/{links.BRANCH}/"
    assert links.DOCS_URL.startswith(prefix)
    assert (ROOT / links.DOCS_URL[len(prefix):]).is_file()


def test_the_readme_the_button_opens_exists():
    assert (ROOT / "README.md").is_file()


def test_pyproject_names_the_same_repository():
    text = (ROOT / "pyproject.toml").read_text()
    urls = dict(re.findall(r'^(\w+) = "(https?://[^"]+)"', text, re.M))
    assert urls["Repository"] == links.REPOSITORY
    assert urls["Homepage"] == links.REPOSITORY
    assert urls["Issues"] == f"{links.REPOSITORY}/issues"


# -- the window ----------------------------------------------------------------
@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
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

    opened = []
    monkeypatch.setattr(MainWindow, "launch_url",
                        staticmethod(lambda url: opened.append(url) or True))
    win = MainWindow()
    qtbot.addWidget(win)
    win.opened = opened
    return win


def test_both_buttons_sit_in_the_status_bar_before_quit(window):
    from writing_habit.gui.qt import QtWidgets
    buttons = window.statusBar().findChildren(QtWidgets.QPushButton)
    assert {window.docs_button, window.readme_button, window.quit_button} <= set(buttons)
    window.show()
    x = {b: b.mapTo(window, b.rect().topLeft()).x()
         for b in (window.docs_button, window.readme_button, window.quit_button)}
    assert x[window.docs_button] < x[window.readme_button] < x[window.quit_button]


def test_the_documentation_button_opens_the_docs(window):
    window.docs_button.click()
    assert window.opened == [links.DOCS_URL]
    assert links.DOCS_URL in window.log.toPlainText()


def test_the_readme_button_opens_the_readme(window):
    window.readme_button.click()
    assert window.opened == [links.README_URL]


def test_the_help_menu_offers_both_pages(window):
    help_menu = next(a.menu() for a in window.menuBar().actions()
                     if a.text() == "&Help")
    actions = {a.text(): a for a in help_menu.actions()}
    actions["&Documentation"].trigger()
    actions["&README on GitHub"].trigger()
    assert window.opened == [links.DOCS_URL, links.README_URL]
    assert "&About" in actions


def test_the_tooltips_name_the_addresses(window):
    assert links.DOCS_URL in window.docs_button.toolTip()
    assert links.README_URL in window.readme_button.toolTip()


def test_a_failure_logs_the_address(window, monkeypatch):
    monkeypatch.setattr(type(window), "launch_url", staticmethod(lambda url: False))
    assert window.open_web_page(links.README_URL) is False
    assert f"The page is {links.README_URL}" in window.log.toPlainText()
