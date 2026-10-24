#!/usr/bin/env python3
"""Regenerate the screenshots of the Tutorials tab from the real window.

The script builds a scratch database from ``examples/tutorial``, drives the
interface offscreen exactly as a reader would, and saves each view into
``src/writing_habit/gui/tutorials/images``. Run it after a change to the window
so the tutorials keep showing the program as it is.

    QT_QPA_PLATFORM=offscreen PYTHONPATH=src python scripts/make_tutorial_images.py

Add ``--coach`` to redraw only the hour view, the review panel, and the coach
dialogs, including the summary for a writing partner, the deadline coverage
check, and the Energy tab.

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


#: Replies llama3.2 gave in a trial run of scripts/try_coach_prompts.py, used
#: so the screenshots show a real model's words without needing a server.
LLAMA_OBJECTIVES = {
    "objectives": ["Find three citations for the rigor section",
                   "Draft second aim's rationale paragraph",
                   "Create a figure legend for the results"],
    "if_then": "If I get distracted by social media, then I will close the "
               "browser and take a 5-minute break",
}


def compose(base, overlay, x, y):
    """Paint ``overlay`` onto a copy of ``base`` at (x, y) and return it."""
    from writing_habit.gui.qt import QtGui
    image = base.toImage().copy()
    painter = QtGui.QPainter(image)
    painter.drawPixmap(x, y, overlay)
    painter.end()
    return QtGui.QPixmap.fromImage(image)


def coach_images(app, window, store):
    """Photograph the shift bar, the review panel, and the coach dialogs."""
    import datetime as dt
    import json
    from writing_habit import coach
    from writing_habit.gui import coach_runner
    from writing_habit.gui.coach_settings import CoachSettingsDialog
    from writing_habit.gui.hour_view import HourPicker
    from writing_habit.gui.qt import QtCore, QtWidgets

    editor = window.editor
    # Wide enough for both button bars, so the Coach menu and the timer show.
    window.resize(1760, 1060)
    editor.set_hour_view(True)
    # Monday at 05:48, inside the A block, so the timer counts down.
    editor.block_timer.now = lambda: dt.datetime(2026, 10, 5, 5, 48)
    editor.block_timer.update_state()
    # Monday's 05:00-06:30 block of project A.
    editor.hour_view.setCurrentIndex(editor.hour_model.index(5, 1))
    editor.hour_view.scrollTo(editor.hour_model.index(4, 1),
                              QtWidgets.QAbstractItemView.PositionAtTop)
    app.processEvents()
    save(window, "hour-view.png")

    # The Coach menu open under its button, over the shift bar.
    bar = editor.coach_button.parentWidget()
    top = editor.shift_buttons[-60].mapTo(editor, QtCore.QPoint(0, 0))
    strip = editor.grab(QtCore.QRect(0, max(top.y() - 6, 0), editor.width(), 300))
    menu = editor.coach_button.menu()
    menu.popup(editor.coach_button.mapToGlobal(
        QtCore.QPoint(0, editor.coach_button.height())))
    app.processEvents()
    corner = editor.coach_button.mapTo(editor, QtCore.QPoint(0, editor.coach_button.height()))
    shot = compose(strip, menu.grab(),
                   min(corner.x(), editor.width() - menu.width() - 4),
                   corner.y() - max(top.y() - 6, 0))
    menu.hide()
    shot = shot.copy(QtCore.QRect(max(shot.width() - 760, 0), 0, 760,
                                  menu.height() + 60))
    OUT.mkdir(parents=True, exist_ok=True)
    shot.save(str(OUT / "coach-menu.png"))
    print(f"Wrote {OUT / 'coach-menu.png'}")
    del bar

    # The picker with the review panel, as a block ends.
    starts = editor.hour_model.blocks_at(5, 1)
    dialog = HourPicker(editor.table, 0, editor.table.day_labels[0], 5,
                        existing=starts, parent=window,
                        monday=editor.week_monday(), review_blocks=starts)
    panel = dialog.review_panel
    panel.runner.background = False
    panel.guard.now = lambda: dt.datetime(2026, 10, 5, 11, 0)
    panel.guard.confirm = lambda text: True
    for text in LLAMA_OBJECTIVES["objectives"]:
        panel.add_objective(text, origin="ai")
    panel.objective_list.item(0).setCheckState(QtCore.Qt.Checked)
    panel.objective_list.item(1).setCheckState(QtCore.Qt.Checked)
    panel.focus_spin.setValue(4)
    panel.interruption_spin.setValue(2)
    panel.output_edit.setText("one paragraph, three citations")
    panel.next_edit.setText("Start the figure legend from the panel notes")
    panel.model_box.setChecked(False)
    panel.run_debrief()
    dialog.show()
    dialog.adjustSize()
    app.processEvents()
    save(dialog, "hour-review.png")
    dialog.reject()

    # The Suggest dialog with llama3.2's objectives.
    answer = coach.Answer(
        data=LLAMA_OBJECTIVES, text="", source="local model llama3.2",
        facts=coach.objective_facts("work on the R01", "1001grantR01", 90,
                                    "2026-11-15"))
    lines = LLAMA_OBJECTIVES["objectives"] + [f"Note: {LLAMA_OBJECTIVES['if_then']}"]
    suggest = coach_runner.SuggestionDialog(
        "Suggested objectives", answer, lines,
        intro="Check the objectives to keep. You can reword them in the list "
              "afterwards.", accept_text="Add the checked ones", parent=window)
    suggest.show()
    suggest.adjustSize()
    app.processEvents()
    save(suggest, "coach-suggest.png")
    suggest.reject()

    # The settings dialog with the models a server reported.
    settings_dialog = CoachSettingsDialog(window)
    settings_dialog.lister = lambda url, api, allow_remote=False: [
        "llama3.2:latest", "qwen2.5:7b"]
    settings_dialog.use_box.setChecked(True)
    settings_dialog.refresh()
    settings_dialog.show()
    settings_dialog.adjustSize()
    app.processEvents()
    save(settings_dialog, "coach-settings.png")
    settings_dialog.reject()

    # The summary for a writing partner, from the tutorial week's plan and the
    # sessions in its mytime.db, with the objectives met in the review above.
    from writing_habit import plan_import
    from writing_habit.track.mytime_sync import sync_mytime
    con = coach_runner.connect(store["db"])
    try:
        if not con.execute("SELECT 1 FROM plan_block LIMIT 1").fetchone():
            plan_import.import_org(con, store["table"], WEEK)
            sync_mytime(con, store["mytime_db"], table=store["table"])
        partner = coach.partner_summary(None, con, WEEK, today="2026-10-10", log=False)
    finally:
        con.close()
    partner_dialog = coach_runner.PartnerDialog(partner, parent=window)
    partner_dialog.show()
    app.processEvents()
    save(partner_dialog, "coach-partner.png")
    partner_dialog.reject()
    plan_check_images(app, window, store)
    del json


#: A sample week for the planning checks, because the tutorial week keeps every
#: deadline covered and fits the default energy profile. Today is its Wednesday.
CHECK_WEEK = (
    "#+TITLE: Sample week for the planning checks\n"
    "|        Time | M  | Tu | W  | Th | F  |\n"
    "|-------------+----+----+----+----+----|\n"
    "| 05:00-06:30 | gA | sE | gC | sE | gC |\n"
    "| 14:00-15:30 |    | gB |    | gC |    |\n"
    "|-------------+----+----+----+----+----|\n"
    "| A: 1001grantR01 2026-10-30 :safe: |  |  |  |  |  |\n"
    "| B: 2002reviewArticle 2027-03-01 :safe: |  |  |  |  |  |\n"
    "| C: 3003methodsNote :risky: |  |  |  |  |  |\n"
    "| E: 9001email @support |  |  |  |  |  |\n"
    "\n"
    "#+NAME: current-semester-projects\n"
    "| - 5005bookChapter 2026-11-02 :safe: |\n"
)


def plan_check_images(app, window, store):
    """Draw the deadline coverage dialog and the Energy tab from the sample week."""
    import datetime as dt

    from writing_habit import coach, deadlines
    from writing_habit.gui import coach_runner

    editor = window.editor
    sample = Path(store["out_dir"]) / "Oct12.org"
    sample.write_text(CHECK_WEEK, encoding="utf-8")
    real_today = editor.today
    editor.today = lambda: dt.date(2026, 10, 14)
    editor.open(str(sample))
    app.processEvents()

    result = editor.coverage_result()
    answer = coach.cover_deadlines(None, result)
    risks = [r for r in result.risks if r.donor is not None]
    dialog = coach_runner.SuggestionDialog(
        "Deadlines and this week's plan", answer,
        [deadlines.proposal_line(r) for r in risks], intro=answer.data["note"],
        accept_text="Make the checked changes", parent=window)
    dialog.show()
    dialog.adjustSize()
    app.processEvents()
    save(dialog, "coach-coverage.png")
    dialog.reject()

    editor.panels.setCurrentWidget(editor.energy_panel)
    editor.energy_panel.grid.scrollToItem(editor.energy_panel.grid.item(4, 0))
    app.processEvents()
    save(editor.panels, "energy-tab.png")
    editor.panels.setCurrentIndex(0)

    editor.today = real_today
    editor.open(store["table"])
    app.processEvents()


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
    # Two waiting tasks, so the review panel's grasscatcher has something to offer.
    with open(table, "a", encoding="utf-8") as fh:
        fh.write("\n#+NAME: grasscatcher\n| A: tidy the budget justification |\n"
                 "| B: reread the reviewer comments |\n")
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
    if "--coach" in sys.argv:
        coach_images(app, window, store)
        window.close()
        return 0
    window.editor.set_hour_view(False)
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

    window.show_tab("Schedule")
    coach_images(app, window, store)

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
