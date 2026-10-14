#!/usr/bin/env python3
"""Regenerate the screenshots of the Tutorials tab from the real window.

The script builds a scratch database from ``examples/tutorial``, drives the
interface offscreen exactly as a reader would, and saves each view into
``src/writing_habit/gui/tutorials/images``. Run it after a change to the window
so the tutorials keep showing the program as it is.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python scripts/make_tutorial_images.py

The dashboard is a web page, so it is drawn by a headless Chromium through
Playwright when that is installed, and skipped with a note otherwise.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EXAMPLE = ROOT / "examples" / "tutorial"
OUT = ROOT / "src" / "writing_habit" / "gui" / "tutorials" / "images"
WEEK = "2026-10-05"


def wait_for(app, panel, timeout_ms=20000):
    """Process events until the panel's worker has finished."""
    from writing_habit.gui.qt import QtCore
    timer = QtCore.QElapsedTimer()
    timer.start()
    while panel.worker is not None and timer.elapsed() < timeout_ms:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
    app.processEvents()


def show_form(window, tab, name):
    """Raise ``tab`` and, when it holds several forms, the one called ``name``."""
    from writing_habit.gui.qt import QtWidgets
    window.show_tab(tab)
    page = window.tabs.currentWidget()
    if isinstance(page, QtWidgets.QToolBox):
        for index in range(page.count()):
            if page.itemText(index).endswith(" " + name):
                page.setCurrentIndex(index)
    return window.panels[name]


def run(app, panel, **values):
    """Fill the form with ``values``, press Run, and wait for the output."""
    for dest, value in values.items():
        panel.fields[dest].set_value(value)
    panel.refresh()
    panel.run()
    wait_for(app, panel)


def save(widget, name):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    widget.grab().save(str(path))
    print(f"Wrote {path}")


def main() -> int:
    from writing_habit import db
    from writing_habit.gui import settings
    from writing_habit.gui.qt import QtWidgets

    # A fixed, readable folder, because its paths appear in the screenshots.
    work = Path(tempfile.gettempdir()) / "writing-habit-tutorial"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    table = work / "week.org"
    shutil.copy(EXAMPLE / "week.org", table)
    mytime = work / "mytime.db"
    shutil.copy(EXAMPLE / "mytime.db", mytime)
    habit = work / "writing-habit.db"
    con = db.connect(str(habit))
    db.init_db(con)
    con.close()

    # The window reads its paths from a scratch store, never from the user's.
    store = {"db": str(habit), "table": str(table), "week": WEEK,
             "out_dir": str(work), "mytime_db": str(mytime)}
    settings.get = lambda key: store.get(key, settings.DEFAULTS[key])
    settings.put = lambda key, value: store.__setitem__(key, value)
    settings.save_window = lambda window: None
    settings.restore_window = lambda window: False

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from writing_habit.gui.mainwindow import MainWindow
    window = MainWindow()
    window.resize(1440, 1060)
    window.log_dock.hide()        # the forms show their own output
    window.show()
    app.processEvents()

    window.show_tab("Schedule")
    window.editor.open(str(table))
    app.processEvents()
    save(window, "schedule.png")
    # Give the legend room for every row, then photograph the legend alone.
    box = window.editor.project_tabs.parentWidget()      # the Legend group box
    split = box.parentWidget()
    if isinstance(split, QtWidgets.QSplitter):
        sizes = split.sizes()
        split.setSizes([sum(sizes) - 330, 330])
        app.processEvents()
        save(box, "legend.png")
    else:
        save(box, "legend.png")

    window.editor.show_list("current-semester-projects")
    app.processEvents()
    save(box, "semester-lists.png")
    window.editor.show_list(None)
    app.processEvents()

    panel = show_form(window, "Plan", "plan import")
    run(app, panel, path=str(table), week=WEEK)
    save(window, "plan.png")

    panel = show_form(window, "Track", "track sync")
    run(app, panel, source=str(mytime))
    save(window, "track-sync.png")

    panel = show_form(window, "Compare", "compare")
    run(app, panel, week=WEEK)
    save(window, "compare.png")

    panel = show_form(window, "Compare", "dashboard")
    page = work / "dashboard.html"
    run(app, panel, week=WEEK, out=str(page))
    window.preview_dock.hide()

    panel = show_form(window, "History", "history")
    run(app, panel)
    save(window, "history.png")

    if window.specs.get("writing-schedule"):
        panel = show_form(window, "Generate", "generate")
        for dest, value in (("table", str(table)), ("week", WEEK),
                            ("dir", str(work / "out"))):
            panel.fields[dest].set_value(value)
        panel.refresh()
        save(window, "generate.png")

    window.show_tab("Tutorials")
    app.processEvents()
    save(window, "tutorials-tab.png")
    window.close()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed, so dashboard.png was not redrawn")
        return 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        tab = browser.new_page(viewport={"width": 1100, "height": 900})
        tab.goto(page.as_uri())
        tab.screenshot(path=str(OUT / "dashboard.png"))
        browser.close()
    print(f"Wrote {OUT / 'dashboard.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
