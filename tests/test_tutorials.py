"""The Tutorials tab, its pages, and the practice week the pages are drawn from."""

import os
import re

import pytest

from writing_habit.gui import tutorials

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PAGE_TEXT = {name: tutorials.page_path(name).read_text(encoding="utf-8")
             for _title, name in tutorials.PAGES}
KEYS = {tutorials.page_key(name) for _title, name in tutorials.PAGES}


@pytest.mark.parametrize("name", sorted(PAGE_TEXT))
def test_every_image_a_page_shows_ships_with_it(name):
    for src in re.findall(r'<img src="([^"]+)"', PAGE_TEXT[name]):
        assert (tutorials.HERE / src).is_file(), src


@pytest.mark.parametrize("name", sorted(PAGE_TEXT))
def test_every_tutorial_link_names_a_page(name):
    for key in re.findall(r'href="tutorial:([^"]+)"', PAGE_TEXT[name]):
        assert key in KEYS, key


@pytest.mark.parametrize("name", sorted(PAGE_TEXT))
def test_every_page_shows_both_routes(name):
    text = PAGE_TEXT[name]
    if name == "troubleshooting.html":
        return
    assert "<pre>" in text, "a command-line example"
    assert "In the window" in text or "href=\"tab:" in text, "a point-and-click route"


def test_the_tab_links_name_real_tabs():
    pytest.importorskip("PyQt5", reason="the graphical extra is not installed")
    from writing_habit.gui import mainwindow
    titles = {entry[0] for entry in mainwindow.TABS} | {mainwindow.TUTORIALS}
    for text in PAGE_TEXT.values():
        for tab in re.findall(r'href="tab:([^"]+)"', text):
            assert tab in titles, tab


def test_the_practice_week_gives_the_numbers_in_the_screenshots(tmp_path):
    pytest.importorskip("writing_schedule")
    from writing_habit import db
    from writing_habit.compare import queries
    from writing_habit.plan_import import import_org
    from writing_habit.track import mytime_sync
    root = tutorials.HERE.parents[3]
    example = root / "examples" / "tutorial"
    con = db.connect(str(tmp_path / "habit.db"))
    db.init_db(con)
    assert import_org(con, str(example / "week.org"), "2026-10-05") == 22
    report = mytime_sync.sync_mytime(con, str(example / "mytime.db"))
    assert (report.inserted, report.skipped_not_in_legend, report.skipped_no_time) == (18, 3, 1)
    names = {r["code"]: r["description"] for r in con.execute("SELECT * FROM project")}
    assert names["A"] == "1001grantR01"              # the deadline is not in the name
    week = queries.week_project(con, "2026-10-05")
    assert sum(r["planned_min"] for r in week) == 1575
    assert sum(r["actual_min"] for r in week) == 1080


@pytest.fixture()
def window(qapp, monkeypatch):
    from writing_habit.gui import mainwindow, settings
    monkeypatch.setattr(settings, "get", lambda key: settings.DEFAULTS[key])
    monkeypatch.setattr(settings, "put", lambda key, value: None)
    monkeypatch.setattr(settings, "save_window", lambda win: None)
    monkeypatch.setattr(settings, "restore_window", lambda win: False)
    win = mainwindow.MainWindow()
    yield win
    win.close()


def test_the_tutorials_tab_holds_one_subtab_per_page(window):
    from writing_habit.gui import mainwindow
    assert window.tabs.tabText(window.tabs.count() - 1) == mainwindow.TUTORIALS
    page = window.tutorials
    assert [page.tabText(i) for i in range(page.count())] == [t for t, _n in tutorials.PAGES]
    for browser in page.browsers.values():
        assert browser.toPlainText().strip()


def test_links_raise_tabs_tutorials_and_the_web(window):
    from writing_habit.gui.qt import QtCore
    opened = []
    window.tutorials.open_url = lambda url: opened.append(url) or True
    assert window.tutorials.follow(QtCore.QUrl("tab:Track")) == "tab"
    assert window.tabs.tabText(window.tabs.currentIndex()) == "Track"
    assert window.tutorials.follow(QtCore.QUrl("tutorial:dashboard")) == "tutorial"
    assert window.tutorials.currentWidget() is window.tutorials.browsers["dashboard"]
    assert window.tutorials.follow(QtCore.QUrl("https://example.org/")) == "web"
    assert opened == ["https://example.org/"]


def test_help_menu_opens_the_tutorials(window):
    from writing_habit.gui import mainwindow
    window.show_tab("Plan")
    window.tutorials_action.trigger()
    assert window.tabs.tabText(window.tabs.currentIndex()) == mainwindow.TUTORIALS
