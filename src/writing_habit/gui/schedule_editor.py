"""The weekly-table view, with the four readings that make a plan reviewable.

The grid answers what the week looks like. Four panels beside it answer whether
the week holds together. The name panel gives the canonical file name for the
grid, or the reason the grid cannot be named. The clashes panel lists the
overlapping blocks and the grid tints the offending cells, which is the
graphical form of ``writing-schedule check``. The totals panel gives planned
minutes by day, by project, and by activity. The legend panel resolves every
project letter against the legend, so an unknown letter shows before the file
is used rather than after.

A cell edit and a legend edit rewrite one line of the file and leave every other
line alone, so a saved table differs from the one on disk only where the writer
changed it. Saving offers the canonical file name when the grid has one.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
from pathlib import Path
from typing import Dict, List, Optional

from .. import name as namemod
from . import external_editor, settings
from .legend_model import (ACTIVITY, ACTIVITY_CHOICES, ActivityDelegate, CODE,
                           DEADLINE, DESCRIPTION, DeadlineDelegate, LegendModel,
                           RISK, RISK_CHOICES, RiskDelegate)
from .qt import Qt, QtGui, QtWidgets, pyqtSignal
from .. import periods as periodsmod
from .. import coach as coachmod, db as dbmod, review as reviewmod
from ..project_lists import (CARRIED, COMPLETED, GRASSCATCHER, HORIZONS, LISTS, WEEKS,
                             list_titles)
from .. import deadlines as deadlinesmod, energy as energymod
from ..project_lists import CURRENT as CURRENT_LIST
from .energy_panel import EnergyPanel
from .periods_dialog import PeriodsDialog
from .project_list_view import ProjectListPanel
from . import coach_runner
from .review_panel import ReviewDialog
from .hour_view import (HOUR_COLUMN, EdgeDragger, HourCellDelegate, HourGridModel,
                        HourPicker)
from .project_tabs import SEMESTER_ROW, WEEK_ROW, ProjectTabs
from .table_model import TIME_COLUMN, CodeDelegate, WeeklyTableModel

import sys as _sys

# Qt reads Ctrl as the Command key on macOS, so QKeySequence.Find is
# Command+F there.  The physical Control key is Meta to Qt, and the tutorial
# says Ctrl+F, so a Mac gets Control+F as well.
FIND_KEYS_TEXT = ("Command+F or Control+F" if _sys.platform == "darwin"
                  else "Ctrl+F")


def find_keys() -> list:
    """Return the key sequences that put the cursor in the Find box.

    Built after the application starts, because Qt looks up the standard
    Find keys in the running platform.
    """
    keys = [QtGui.QKeySequence(QtGui.QKeySequence.Find)]
    if _sys.platform == "darwin":
        keys.append(QtGui.QKeySequence("Meta+F"))
    if keys[0].isEmpty():
        keys[0] = QtGui.QKeySequence("Ctrl+F")
    return keys
from .weekly_table import BLOCK, PROJECT_CODES, SECTION, WeeklyTable, split_due_date

#: The shift buttons, as (minutes, label, hour-view keys), earliest first.
SHIFT_STEPS = [
    (-60, "Earlier 1 h", "Alt+Shift+Up"),
    (-15, "Earlier 15 min", "Alt+Up"),
    (15, "Later 15 min", "Alt+Down"),
    (60, "Later 1 h", "Alt+Shift+Down"),
]

#: The title of the tab that holds this week's legend, before its count.
LEGEND_TAB = "This week"

#: The template styles offered by New from template, as (label, style).
TEMPLATE_CHOICES = [
    ("Standard day (nine blocks)", "standard"),
    ("Morning writer (three blocks)", "morning"),
    ("Evening writer (three blocks)", "evening"),
    ("Split day (three blocks)", "split"),
]


def _plain(read_only: bool = True) -> QtWidgets.QPlainTextEdit:
    widget = QtWidgets.QPlainTextEdit()
    widget.setReadOnly(read_only)
    return widget


class ScheduleEditor(QtWidgets.QWidget):
    """Open a weekly table, show it, and report what it says."""

    logged = pyqtSignal(str)
    opened = pyqtSignal(str)
    saved = pyqtSignal(str)
    edited = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.table: Optional[WeeklyTable] = None
        self.model = WeeklyTableModel(parent=self)

        outer = QtWidgets.QVBoxLayout(self)

        bar = QtWidgets.QHBoxLayout()
        self.open_button = QtWidgets.QPushButton("Open table")
        self.open_button.clicked.connect(self.choose)
        self.new_button = QtWidgets.QPushButton("New from template")
        # clicked carries a checked flag, which would arrive as the project
        # count, so the slot is called with no argument at all.
        self.new_button.clicked.connect(lambda: self.scaffold())
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        self.save_as_button = QtWidgets.QPushButton("Save as")
        self.save_as_button.clicked.connect(self.save_as)
        self.rename_button = QtWidgets.QPushButton("Rename to canonical")
        self.rename_button.setToolTip(
            "Move the file to the name its grid gives it, so the tracker files "
            "the week under the right schedule shape")
        self.rename_button.clicked.connect(self.rename_to_canonical)
        self.reload_button = QtWidgets.QPushButton("Reload")
        self.reload_button.clicked.connect(self.reload)
        self.external_button = QtWidgets.QPushButton("Open in editor")
        self.external_button.setToolTip(
            "Open the table file in the editor named by WHGEDITOR in ~/.bashrc, "
            "or in the system's default text editor. Press Reload after saving "
            "there.")
        self.external_button.clicked.connect(lambda: self.open_externally())
        self.insert_above_button = QtWidgets.QPushButton("Insert above")
        self.insert_above_button.setToolTip(
            "Add an empty time block above the selected row")
        self.insert_above_button.clicked.connect(lambda: self.insert_row(above=True))
        self.insert_below_button = QtWidgets.QPushButton("Insert below")
        self.insert_below_button.setToolTip(
            "Add an empty time block below the selected row")
        self.insert_below_button.clicked.connect(lambda: self.insert_row(above=False))
        self.move_up_button = QtWidgets.QPushButton("Move up")
        self.move_up_button.setToolTip(
            "Shift the selected time block one row up (Alt+Up). Past a section "
            "header it joins the section above.")
        self.move_up_button.clicked.connect(lambda: self.move_row(up=True))
        self.move_down_button = QtWidgets.QPushButton("Move down")
        self.move_down_button.setToolTip(
            "Shift the selected time block one row down (Alt+Down). Past a "
            "section header it joins the section below.")
        self.move_down_button.clicked.connect(lambda: self.move_row(up=False))
        self.delete_row_button = QtWidgets.QPushButton("Delete row")
        self.delete_row_button.setToolTip(
            "Delete the selected time block. A section header and the legend "
            "stay.")
        self.delete_row_button.clicked.connect(lambda: self.delete_row())
        self.hour_button = QtWidgets.QPushButton("Hour view")
        self.hour_button.setCheckable(True)
        self.hour_button.setToolTip(
            "Show the week as 24 hour rows. Double-click a cell, or press "
            "Enter, to place a block from a grid of ranges. The file keeps its "
            "rows either way.")
        self.hour_button.toggled.connect(self.set_hour_view)
        self.more_button = QtWidgets.QToolButton()
        self.more_button.setText("More")
        self.more_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        more_menu = QtWidgets.QMenu(self.more_button)
        self.activities_action = more_menu.addAction("Move activities into cells")
        self.activities_action.setToolTip(
            "Write each section's activity letter into the cells under it, "
            "such as gA, so the section rows are no longer needed")
        self.activities_action.triggered.connect(
            lambda: self.move_activities_into_cells())
        self.split_blocks_action = more_menu.addAction("Move extra legend blocks into the lists")
        self.split_blocks_action.setToolTip(
            "For a table in the older layout, where the semester lists sat in "
            "the legend separated by rules: keep the first block as this week's "
            "legend and move the next blocks to the current, next, and later "
            "semester lists, after showing the moves")
        self.split_blocks_action.triggered.connect(lambda: self.split_legend_blocks())
        self.tidy_legend_action = more_menu.addAction("Split legend into project and deadline")
        self.tidy_legend_action.setToolTip(
            "Rewrite each legend description as a project name and a "
            "YYYY-MM-DD deadline, after showing what changes")
        self.tidy_legend_action.triggered.connect(lambda: self.tidy_legend())
        self.drop_rows_action = more_menu.addAction("Drop unused time rows")
        self.drop_rows_action.setToolTip(
            "Delete every time-block row with no filled cell, after asking. "
            "The printed sheets do not change, because they draw every hour "
            "whatever rows the table holds.")
        self.drop_rows_action.triggered.connect(lambda: self.drop_unused_rows())
        self.more_button.setMenu(more_menu)
        self.path_label = QtWidgets.QLabel("No table open")
        # A long path would otherwise set the window's minimum width.
        self.path_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored,
                                      QtWidgets.QSizePolicy.Preferred)
        for button in (self.hour_button, self.open_button, self.new_button,
                       self.save_button,
                       self.save_as_button, self.rename_button, self.reload_button,
                       self.external_button, self.insert_above_button,
                       self.insert_below_button, self.move_up_button,
                       self.move_down_button, self.delete_row_button,
                       self.more_button):
            bar.addWidget(button)
        bar.addWidget(self.path_label, 1)
        outer.addLayout(bar)

        # A second bar shifts the selected block in time, in either view.
        shift_bar = QtWidgets.QHBoxLayout()
        shift_bar.addWidget(QtWidgets.QLabel("Shift the selected block:"))
        self.shift_buttons = {}
        for minutes, label, keys in SHIFT_STEPS:
            button = QtWidgets.QPushButton(label)
            when = "earlier" if minutes < 0 else "later"
            size = (f"{abs(minutes) // 60} hour" if abs(minutes) >= 60
                    else f"{abs(minutes)} minutes")
            button.setToolTip(
                f"Move the selected block {size} {when} ({keys} in the hour "
                "view). With Push checked, the later blocks it would overlap "
                "move down too.")
            button.clicked.connect(lambda _c=False, m=minutes: self.shift_selected(m))
            button.setEnabled(False)
            self.shift_buttons[minutes] = button
            shift_bar.addWidget(button)
        self.push_box = QtWidgets.QCheckBox("Push later blocks down")
        self.push_box.setToolTip(
            "When a placed or shifted block overlaps a block that starts after "
            "it on the same day, move that block down to start where this one "
            "ends, and so on down the day. Blocks that start earlier never "
            "move.")
        self.push_box.setChecked(settings.get("push_blocks") != "false")
        self.push_box.toggled.connect(
            lambda on: settings.put("push_blocks", "true" if on else "false"))
        shift_bar.addWidget(self.push_box)
        shift_bar.addStretch(1)
        from .block_timer import BlockTimerButton
        self.block_timer = BlockTimerButton(
            lambda: self.table.blocks() if self.table is not None else [],
            self.week_monday, self)
        self.block_timer.select_requested.connect(self.select_block)
        self.block_timer.review_requested.connect(lambda b: self.open_review(b))
        shift_bar.addWidget(self.block_timer)
        from .pomodoro import PomodoroTimer
        self.pomodoro = PomodoroTimer(self.pomodoro_block, self)
        self.pomodoro.logged.connect(self.logged)
        shift_bar.addWidget(self.pomodoro)
        self.review_button = QtWidgets.QPushButton("Objectives and review")
        self.review_button.setToolTip(
            "Set the selected block's objectives before it starts, and rate "
            "its focus and interruptions when it ends. Stored in the habit "
            "database, where track sync never writes.")
        self.review_button.setEnabled(False)
        self.review_button.clicked.connect(lambda: self.open_review())
        shift_bar.addWidget(self.review_button)
        # The coach: Rule 7 readings and the Rule 10 switches.
        self.coach_button = QtWidgets.QToolButton()
        self.coach_button.setText("Coach")
        self.coach_button.setToolTip(
            "Readings of your record from the coach, and its switches. The "
            "coach uses a model on this computer when it is turned on, and "
            "plain summaries otherwise.")
        self.coach_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        coach_menu = QtWidgets.QMenu(self.coach_button)
        self.read_weeks_action = coach_menu.addAction("Read my weeks")
        self.read_weeks_action.setToolTip(
            "The two strongest patterns in how you keep your plan, by weekday, "
            "schedule shape, event, and month, and one change to try")
        self.read_weeks_action.triggered.connect(lambda: self.read_weeks())
        self.size_week_action = coach_menu.addAction("Size this week's plan")
        self.size_week_action.setToolTip(
            "A plan size drawn from the minutes you actually wrote in recent "
            "weeks like this one")
        self.size_week_action.triggered.connect(lambda: self.size_week())
        self.coverage_action = coach_menu.addAction("Check deadline coverage")
        self.coverage_action.setToolTip(
            "Find the projects due in the next few weeks that have no block "
            "left this week, and propose a block to give each one (Rule 3)")
        self.coverage_action.triggered.connect(lambda: self.check_coverage())
        self.energy_action = coach_menu.addAction("Match blocks to my energy")
        self.energy_action.setToolTip(
            "Find the blocks whose hours do not suit their kind of writing, by "
            "your energy profile, and propose swaps (Rule 2)")
        self.energy_action.triggered.connect(lambda: self.match_energy())
        self.rescue_action = coach_menu.addAction("Rescue missed blocks")
        self.rescue_action.setToolTip(
            "Find this week's blocks that passed with nothing tracked, and "
            "propose a slot to make up each one worth rescuing, or say to let "
            "it go (Rule 9)")
        self.rescue_action.triggered.connect(lambda: self.rescue_missed())
        self.misses_action = coach_menu.addAction("Ask about missed blocks")
        self.misses_action.setToolTip(
            "One question about each block of the week that was missed, for you "
            "to answer in a sentence. The coach asks and never supplies a reason "
            "(Rule 6).")
        self.misses_action.triggered.connect(lambda: self.ask_misses())
        self.numbering_action = coach_menu.addAction("Number a new project...")
        self.numbering_action.setToolTip(
            "Suggest a free four-digit number near the related projects, from "
            "your project folders and lists, and flag a project that may be "
            "forming inside another. Nothing is renamed or moved.")
        self.numbering_action.triggered.connect(lambda: self.number_project())
        self.triage_action = coach_menu.addAction("Triage carried projects")
        self.triage_action.setToolTip(
            "Suggest keeping, deferring, or dropping each project on the Carried "
            "over list, from the minutes logged for it, the last week it was "
            "worked, and its deadline. Only the checked suggestions are applied.")
        self.triage_action.triggered.connect(lambda: self.triage_carried())
        self.stuck_action = coach_menu.addAction("Find stuck projects")
        self.stuck_action.setToolTip(
            "Name the projects of this week that keep missing their objectives "
            "or keep the same next step, so you can break the work down")
        self.stuck_action.triggered.connect(lambda: self.find_stuck())
        self.progress_plan_action = coach_menu.addAction("Plan next week from progress")
        self.progress_plan_action.setToolTip(
            "Share next week's writing hours among the unfinished projects of the "
            "Progress tab by their importance weights, never more than a project "
            "has left, and place the blocks in the hours your energy profile rates "
            "best. The checked projects can be added to the Next week list.")
        self.progress_plan_action.triggered.connect(lambda: self.plan_from_progress())
        self.plan_message_action = coach_menu.addAction("Monday message for my partner")
        self.plan_message_action.setToolTip(
            "A short message that tells your accountability partner the week's "
            "plan: the hours, the main projects, and the one that matters most. "
            "You edit it and send it yourself (Rule 8).")
        self.plan_message_action.triggered.connect(lambda: self.plan_message())
        self.partner_action = coach_menu.addAction("Summary for my partner")
        self.partner_action.setToolTip(
            "A short message about the open week for your accountability "
            "partner, with the share of the plan kept and the objectives met. "
            "You edit it and send it yourself (Rule 8).")
        self.partner_action.triggered.connect(lambda: self.partner_summary())
        self.semester_action = coach_menu.addAction("Semester review")
        self.semester_action.setToolTip(
            "A short narrative of the semester for an annual faculty report: the "
            "time planned and written, the share kept by month, the projects "
            "completed, and objectives met. Run it before rolling forward.")
        self.semester_action.triggered.connect(lambda: self.semester_review())
        coach_menu.addSeparator()
        self.coach_settings_action = coach_menu.addAction("Settings...")
        self.coach_settings_action.setToolTip(
            "Choose the local model from the ones the server has installed, "
            "and the server's address and interface")
        self.coach_settings_action.triggered.connect(lambda: self.open_coach_settings())
        self.model_action = coach_menu.addAction("Use the local model")
        self.model_action.setCheckable(True)
        self.model_action.setChecked(settings.get("ai_debrief") == "true")
        self.model_action.toggled.connect(
            lambda on: settings.put("ai_debrief", "true" if on else "false"))
        self.ai_off_action = coach_menu.addAction("AI off this week")
        self.ai_off_action.setCheckable(True)
        self.ai_off_action.setToolTip(
            "Run this week without the coach, to check that the habit holds "
            "on its own (Rule 10)")
        self.ai_off_action.toggled.connect(lambda on: self.set_ai_off(on))
        self.coach_button.setMenu(coach_menu)
        shift_bar.addWidget(self.coach_button)
        outer.addLayout(shift_bar)
        for button in (self.save_button, self.save_as_button,
                       self.rename_button, self.reload_button,
                       self.external_button, self.insert_above_button,
                       self.insert_below_button, self.move_up_button,
                       self.move_down_button, self.delete_row_button,
                       self.hour_button, self.more_button):
            button.setEnabled(False)

        #: Starts the external editor.  A test replaces it to run nothing.
        self.launch_editor = external_editor.open_in_editor

        splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.view = QtWidgets.QTableView()
        self.view.setModel(self.model)
        # Rows are shaded by start-time group in the model rather than one by
        # one, so the choices for one start time read as a set.
        self.view.setAlternatingRowColors(False)
        self.view.horizontalHeader().setStretchLastSection(False)
        self.view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.view.setItemDelegate(CodeDelegate(self.view))
        self.model.edited.connect(self.on_grid_edit)
        self.view.selectionModel().currentChanged.connect(
            lambda *_args: self._on_current_changed())
        self.hour_model = HourGridModel(parent=self)
        self.hour_view = QtWidgets.QTableView()
        self.hour_view.setModel(self.hour_model)
        self.hour_view.setItemDelegate(HourCellDelegate(self.hour_view))
        self.edge_dragger = EdgeDragger(
            self.hour_view,
            lambda block, start, end, offset: self.drag_block(block, start, end, offset))
        self.hour_view.setAlternatingRowColors(False)
        self.hour_view.setWordWrap(True)
        self.hour_view.verticalHeader().setVisible(False)
        self.hour_view.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents)
        self.hour_view.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.hour_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.hour_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.hour_view.doubleClicked.connect(self.open_picker)
        for keys in ("Return", "Enter"):
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self.hour_view)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(
                lambda: self.open_picker(self.hour_view.currentIndex()))
        for minutes, _label, keys in SHIFT_STEPS:
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self.hour_view)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(
                lambda m=minutes: self.shift_selected(m))
        self.hour_view.selectionModel().currentChanged.connect(
            lambda *_args: self._update_shift_buttons())
        #: Runs coach work off the window's thread, and checks Rule 10 first.
        self.coach_runner = coach_runner.Runner(self)
        self.coach_guard = coach_runner.Guard(
            lambda: self.table.blocks() if self.table is not None else [],
            self.week_monday, self)
        #: Shows a coach reply and returns whether it was accepted.
        self.run_coach_dialog = (
            lambda dialog: dialog.exec_() == QtWidgets.QDialog.Accepted)
        #: Lists a server's models, and runs the Coach settings dialog.  Tests
        #: replace both.
        self.list_models = coachmod.list_models
        self.run_coach_settings = (
            lambda dialog: dialog.exec_() == QtWidgets.QDialog.Accepted)
        #: Runs the review dialog.  A test replaces it.
        self.run_review = lambda dialog: dialog.exec_()
        #: Runs the picker dialog and returns whether it was accepted. A test
        #: replaces it to answer without showing a window.
        self.run_picker = lambda dialog: dialog.exec_() == QtWidgets.QDialog.Accepted
        self.grid_stack = QtWidgets.QStackedWidget()
        self.grid_stack.addWidget(self.view)
        self.grid_stack.addWidget(self.hour_view)
        splitter.addWidget(self.grid_stack)
        # Alt+Up and Alt+Down move the selected block, as M-up and M-down move
        # a row of an org table in Emacs. The shortcuts belong to the grid, so
        # they do nothing while the legend or a form has the focus.
        for keys, up in (("Alt+Up", True), ("Alt+Down", False)):
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self.view)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda up=up: self.move_row(up=up))

        self.panels = QtWidgets.QTabWidget()
        self.name_panel = _plain()
        self.clash_panel = _plain()
        self.totals_panel = _plain()
        self.legend_panel = _plain()
        self.break_panel = _plain()
        self.panels.addTab(self.name_panel, "Name")
        self.panels.addTab(self.clash_panel, "Clashes")
        self.panels.addTab(self.break_panel, "Breaks")
        self.panels.addTab(self.totals_panel, "Totals")
        self.panels.addTab(self.legend_panel, "Legend")
        self.energy_panel = EnergyPanel(energymod.load(settings.get("energy_profile")))
        self.energy_panel.changed.connect(self.on_energy_changed)
        self.energy_panel.match_requested.connect(lambda: self.match_energy())
        self.energy_panel.suggest_requested.connect(lambda: self.energy_from_reviews())
        self.panels.addTab(self.energy_panel, "Energy")
        splitter.addWidget(self.panels)
        splitter.setSizes([620, 380])

        self.legend_model = LegendModel(parent=self)
        self.legend_model.edited.connect(self.on_edit)
        self.legend_view = QtWidgets.QTableView()
        self.legend_view.setModel(self.legend_model)
        self.legend_view.setItemDelegateForColumn(RISK, RiskDelegate(self.legend_view))
        self.legend_view.setItemDelegateForColumn(
            DEADLINE, DeadlineDelegate(self.legend_view))
        self.legend_view.setItemDelegateForColumn(
            ACTIVITY, ActivityDelegate(self.legend_view))
        self.legend_view.horizontalHeader().setStretchLastSection(False)
        self._fit_legend_columns()

        rows = QtWidgets.QSplitter(Qt.Vertical)
        rows.addWidget(splitter)
        legend_box = QtWidgets.QGroupBox("Projects")
        legend_layout = QtWidgets.QVBoxLayout(legend_box)
        legend_bar = QtWidgets.QHBoxLayout()
        self.project_above_button = QtWidgets.QPushButton("Insert project above")
        self.project_above_button.setToolTip(
            "Add a project to the legend above the selected project")
        self.project_above_button.clicked.connect(
            lambda: self.insert_project(above=True))
        self.project_below_button = QtWidgets.QPushButton("Insert project below")
        self.project_below_button.setToolTip(
            "Add a project to the legend below the selected project, or at "
            "the end when none is selected")
        self.project_below_button.clicked.connect(
            lambda: self.insert_project(above=False))
        self.project_up_button = QtWidgets.QPushButton("Move project up")
        self.project_up_button.setToolTip(
            "Shift the selected project one row up in the legend (Alt+Up)")
        self.project_up_button.clicked.connect(
            lambda: self.move_project(up=True))
        self.project_down_button = QtWidgets.QPushButton("Move project down")
        self.project_down_button.setToolTip(
            "Shift the selected project one row down in the legend (Alt+Down)")
        self.project_down_button.clicked.connect(
            lambda: self.move_project(up=False))
        self.delete_project_button = QtWidgets.QPushButton("Delete project")
        self.delete_project_button.setToolTip(
            "Delete the selected project from the legend")
        self.delete_project_button.clicked.connect(lambda: self.delete_project())
        for button in (self.project_above_button, self.project_below_button,
                       self.project_up_button, self.project_down_button,
                       self.delete_project_button):
            button.setEnabled(False)
            legend_bar.addWidget(button)
        self.sort_legend_button = QtWidgets.QPushButton("Sort by number")
        self.sort_legend_button.setToolTip(
            "Order this week's projects by the four-digit number that starts "
            "each name")
        self.sort_legend_button.setEnabled(False)
        self.sort_legend_button.clicked.connect(lambda: self.sort_legend())
        legend_bar.addWidget(self.sort_legend_button)
        self.periods_button = QtWidgets.QPushButton("Periods")
        self.periods_button.setToolTip(
            "Edit the calendar of semesters, quarters, or fiscal years that names "
            "the project lists, in periods.org beside the tables")
        self.periods_button.clicked.connect(lambda: self.open_periods())
        legend_bar.addWidget(self.periods_button)
        legend_bar.addStretch(1)
        # The same keys as the grid. Each shortcut belongs to its own view, so
        # Alt+Up moves a block when the grid has the focus and a project when
        # the legend has it.
        for keys, up in (("Alt+Up", True), ("Alt+Down", False)):
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self.legend_view)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda up=up: self.move_project(up=up))
        self.legend_view.selectionModel().currentChanged.connect(
            lambda *_args: self._update_project_move_buttons())
        # The week's legend shares the box with the semester project lists,
        # one tab each, so the legend can stay short.
        legend_page = QtWidgets.QWidget()
        page_layout = QtWidgets.QVBoxLayout(legend_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addLayout(legend_bar)
        page_layout.addWidget(self.legend_view)
        # Two rows of buttons choose the page: the weeks, with the grasscatcher
        # at their end, and below them the semesters.
        self.project_tabs = ProjectTabs()
        self.project_tabs.addTab(legend_page, LEGEND_TAB, WEEK_ROW)
        self.list_panels = {}
        for name, title in LISTS:
            panel = ProjectListPanel(name, title, self)
            panel.edited.connect(self.on_list_edit)
            panel.copied.connect(self.on_copied_to_legend)
            panel.moved.connect(self.on_moved_between_lists)
            panel.logged.connect(self.logged)
            panel.commit_requested.connect(
                lambda position: self.commit_grasscatcher(position))
            panel.rank_requested.connect(lambda: self.rank_grasscatcher())
            panel.sync_requested.connect(lambda: self.sync_todos())
            panel.capture_requested.connect(lambda text: self.capture_task(text))
            panel.triage_requested.connect(lambda: self.triage_carried())
            self.list_panels[name] = panel
            self.project_tabs.addTab(
                panel, title, WEEK_ROW if name in WEEKS or name == GRASSCATCHER
                else SEMESTER_ROW)
        names = [name for name, _t in LISTS]
        self.project_tabs.order_row(
            WEEK_ROW, [0] + [1 + names.index(n) for n in WEEKS + [GRASSCATCHER]])
        self.legend_model.modelReset.connect(self._refresh_lists)
        # A banner above the tabs offers to file the lists under a period, or
        # to roll them forward when a new period has begun.
        self.period_banner = QtWidgets.QFrame()
        self.period_banner.setObjectName("periodBanner")
        self.period_banner.setStyleSheet(
            "#periodBanner { background: #fff4d6; border: 1px solid #e0c060; }")
        banner_row = QtWidgets.QHBoxLayout(self.period_banner)
        banner_row.setContentsMargins(6, 3, 6, 3)
        self.period_label = QtWidgets.QLabel()
        self.period_label.setWordWrap(True)
        self.period_choice = QtWidgets.QComboBox()
        self.period_file_button = QtWidgets.QPushButton("File under this period")
        self.period_file_button.clicked.connect(
            lambda: self.file_lists_under(self.period_choice.currentText()))
        self.roll_button = QtWidgets.QPushButton("Roll forward")
        self.roll_button.clicked.connect(lambda: self.roll_forward())
        banner_row.addWidget(self.period_label, 1)
        banner_row.addWidget(self.period_choice)
        banner_row.addWidget(self.period_file_button)
        banner_row.addWidget(self.roll_button)
        self.period_banner.setVisible(False)
        # A note above the tabs says what the reader changed to bring a file
        # in another layout to the standard one, so nothing changes unseen.
        self.layout_banner = QtWidgets.QLabel()
        self.layout_banner.setObjectName("layoutBanner")
        self.layout_banner.setWordWrap(True)
        self.layout_banner.setStyleSheet(
            "#layoutBanner { background: #e8f1fb; border: 1px solid #8fb3dc; "
            "padding: 4px; }")
        self.layout_banner.setVisible(False)
        legend_layout.addWidget(self.layout_banner)
        # The search box filters every project tab and tints the matching
        # projects' cells in the grid, so a name is found without scrolling.
        search_row = QtWidgets.QHBoxLayout()
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setObjectName("findBox")
        self.search_box.setPlaceholderText(
            f"Find a project or task by name or code ({FIND_KEYS_TEXT}). Enter "
            "goes to the next tab with a match. Esc clears.")
        self.search_box.setToolTip(
            f"Type part of a project name or a legend code ({FIND_KEYS_TEXT})")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(lambda _text: self.apply_search())
        self.search_box.returnPressed.connect(lambda: self.next_match())
        # The button does what Enter does, so a reader who does not know the
        # keys can still step from one tab with a match to the next.
        self.find_button = QtWidgets.QPushButton("Find next")
        self.find_button.setToolTip(
            "Go to the next project tab with a match, or put the cursor in "
            "the Find box when it is empty")
        self.find_button.clicked.connect(lambda: self.find_clicked())
        self.search_status = QtWidgets.QLabel()
        find_label = QtWidgets.QLabel("&Find")
        find_label.setBuddy(self.search_box)
        search_row.addWidget(find_label)
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(self.find_button)
        search_row.addWidget(self.search_status)
        legend_layout.addLayout(search_row)
        # The window-wide context lets the keys work right after a click on
        # the Schedule tab, when the focus still sits on the tab bar.  Qt fires
        # a shortcut only while its widget is visible, so the keys do nothing
        # on the other tabs.
        self.find_shortcuts = []
        for keys in find_keys():
            find = QtWidgets.QShortcut(keys, self)
            find.setContext(Qt.WindowShortcut)
            find.activated.connect(lambda: self.focus_search())
            self.find_shortcuts.append(find)
        capture = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Shift+G"), self)
        capture.setContext(Qt.WindowShortcut)
        capture.activated.connect(lambda: self.focus_capture())
        self.capture_shortcut = capture
        clear = QtWidgets.QShortcut(QtGui.QKeySequence("Escape"), self.search_box)
        clear.setContext(Qt.WidgetShortcut)
        clear.activated.connect(self.search_box.clear)
        #: Grid tab name -> (matches, rows) while the search box holds text.
        self._search_counts = {}
        legend_layout.addWidget(self.period_banner)
        legend_layout.addWidget(self.project_tabs)
        #: The calendar of planning periods, or ``None`` when there is none.
        self.calendar: Optional[periodsmod.Calendar] = None
        self.calendar_file: Optional[Path] = None
        #: Today's date.  A test replaces it.
        self.today = _dt.date.today
        #: Runs the Periods dialog.  A test replaces it.
        self.run_periods = lambda dialog: dialog.exec_() == QtWidgets.QDialog.Accepted
        rows.addWidget(legend_box)
        rows.setSizes([520, 220])
        outer.addWidget(rows, 1)

        self.note = QtWidgets.QLabel(
            "<i>A cell takes a legend code. An edit rewrites one line of the "
            "file; the rest is left alone. Select a time to tint in yellow the "
            "rows that do not overlap it. Alt+Up and Alt+Down move the "
            "selected block. A code is one letter, or two letters such as AB "
            "once A to Z are taken. A lowercase g, e, or s before a code, as in "
            "eA, sets the activity of that block; otherwise the project's "
            "default activity or the section decides. Hour view shows 24 hour rows; "
            "double-click a cell there to place a block from a grid of ranges, "
            "and to set its objectives and review. In the hour view, Alt+Up "
            "and Alt+Down shift the selected block by 15 minutes, with Shift "
            "by an hour.</i>")
        self.note.setWordWrap(True)
        outer.addWidget(self.note)

    # -- semester project lists ---------------------------------------------
    def _refresh_lists(self) -> None:
        """Show the open table's lists, and their sizes in the tab titles."""
        for panel in self.list_panels.values():
            if panel.table is not self.table:
                panel.set_table(self.table)
        self._title_lists()

    # -- the search box ----------------------------------------------------
    def focus_search(self) -> None:
        """Put the cursor in the Find box with its text selected."""
        self.search_box.setFocus(Qt.ShortcutFocusReason)
        self.search_box.selectAll()

    def find_clicked(self) -> Optional[int]:
        """Step to the next match, or focus the empty Find box."""
        if not self.search_query():
            self.focus_search()
            return None
        return self.next_match()

    def search_query(self) -> str:
        box = getattr(self, "search_box", None)
        return box.text().strip().lower() if box is not None else ""

    @staticmethod
    def _matches(query: str, code: Optional[str], text: str) -> bool:
        if not query:
            return True
        return query == (code or "").lower() or query in (text or "").lower()

    def _filter_rows(self) -> dict:
        """Hide the rows that do not match the search.  Return the counts.

        The counts are ``{name: (matches, rows)}`` with ``None`` for the legend.
        Rows are hidden in the views, not removed from the models, so every
        button keeps working on the row it points at.
        """
        query = self.search_query()
        counts = {}
        codes = set()
        legend_rows = self.table.legend_rows() if self.table is not None else []
        shown = 0
        for i, document_row in enumerate(legend_rows):
            code, description, _risk = self.table.rows[document_row].parsed
            hit = self._matches(query, code, f"{code} {description}")
            self.legend_view.setRowHidden(i, not hit)
            if hit:
                shown += 1
                if query:
                    codes.add(code)
        counts[None] = (shown, len(legend_rows))
        for name, panel in self.list_panels.items():
            entries = panel.model.entries()
            shown = 0
            for i, entry in enumerate(entries):
                hit = self._matches(query, entry.code,
                                    f"{entry.code or ''} {entry.description}")
                panel.view.setRowHidden(i, not hit)
                shown += hit
            counts[name] = (shown, len(entries))
        self.model.set_highlight(codes)
        self.hour_model.set_highlight(codes)
        self._search_counts = counts if query else {}
        if not hasattr(self, "search_status"):
            return counts
        if query:
            total = sum(m for m, _n in counts.values())
            self.search_status.setText(f"{total} match(es)" if total else "no match")
        else:
            self.search_status.setText("")
        return counts

    def apply_search(self) -> None:
        """Filter the project tabs and tint the grid for the search box."""
        self._title_lists()

    def _count_text(self, name, count: int) -> str:
        found = self._search_counts.get(name)
        if found is not None and count:
            return f"({found[0]} of {count})"
        return f"({count})" if count else ""

    def next_match(self) -> Optional[int]:
        """Raise the next tab with a match and select its first match."""
        if not self.search_query():
            return None
        order = [None] + [name for name, _t in LISTS]
        start = self.project_tabs.currentIndex()
        for step in range(1, len(order) + 1):
            index = (start + step) % len(order)
            name = order[index]
            if self._search_counts.get(name, (0, 0))[0] and \
                    self.project_tabs.isTabVisible(index):
                self.project_tabs.setCurrentIndex(index)
                view = self.legend_view if name is None else self.list_panels[name].view
                for row in range(view.model().rowCount()):
                    if not view.isRowHidden(row):
                        view.setCurrentIndex(view.model().index(row, 1))
                        break
                return index
        return None

    def _title_lists(self) -> None:
        """Put each tab's project count in its title, as in This week (9)."""
        self._filter_rows()
        legend_count = self.legend_model.rowCount()
        self.project_tabs.setTabText(
            0, f"{LEGEND_TAB} {self._count_text(None, legend_count)}".strip()
            if self._search_counts else f"{LEGEND_TAB} ({legend_count})")
        self.sort_legend_button.setEnabled(self.legend_model.rowCount() > 1)
        titles, tips = self.list_titles()
        if self.table is not None:
            # A file in columns shows each list's title as its caption.
            self.table.list_titles = dict(titles)
        for index, (name, _plain_title) in enumerate(LISTS, start=1):
            title = titles[name]
            panel = self.list_panels[name]
            panel.title = title
            count = panel.model.rowCount()
            self.project_tabs.setTabText(
                index, f"{title} {self._count_text(name, count)}".strip())
            self.project_tabs.setTabToolTip(index, tips.get(name, ""))
            if name == CARRIED:
                # The list exists only between a roll forward and its review.
                self.project_tabs.setTabVisible(index, bool(count))

    def show_list(self, name: Optional[str] = None) -> None:
        """Raise the tab of list ``name``, or the legend when ``name`` is ``None``."""
        panel = self.list_panels.get(name) if name else None
        self.project_tabs.setCurrentIndex(
            self.project_tabs.indexOf(panel) if panel is not None else 0)

    def sort_legend(self) -> bool:
        """Order this week's legend by project number.  Say whether it moved."""
        if self.table is None or not self.table.sort_legend():
            return False
        self._rebuild_views()
        self.logged.emit("Sorted this week's projects by project number")
        self.on_edit()
        return True

    def on_moved_between_lists(self, target: str) -> None:
        """A project went to list ``target``, so show it there too."""
        panel = self.list_panels.get(target)
        if panel is not None:
            panel.set_table(self.table)
        self._title_lists()

    def on_list_edit(self) -> None:
        self._title_lists()
        self.on_edit()

    def on_copied_to_legend(self, at: int) -> None:
        """A project came over from a list, so show it in the legend."""
        self.legend_model.set_table(self.table)
        self._fit_legend_columns()
        self.show_list(None)
        legend_row = self.legend_model._rows.index(at)
        self.legend_view.setCurrentIndex(self.legend_model.index(legend_row, DESCRIPTION))
        self.on_edit()

    # -- layout ------------------------------------------------------------
    def _fit_columns(self) -> None:
        """Size the Time column to its text and share the rest among the days.

        Sizing every column to its contents collapses the seven day columns,
        because a cell holds one letter, and a stretching last section then
        swallows the width they gave up, which is why Sunday ended up wider
        than the other six put together. Stretching the day columns instead
        gives each an equal share of whatever the window offers, and keeps them
        equal when the window is resized.
        """
        header = self.view.horizontalHeader()
        header.setStretchLastSection(False)
        columns = self.model.columnCount()
        if not columns:
            return
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        for column in range(1, columns):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.Stretch)

    def _fit_legend_columns(self) -> None:
        """Give the legend's width to the project name, which is the long field."""
        header = self.legend_view.horizontalHeader()
        header.setStretchLastSection(False)
        modes = {CODE: QtWidgets.QHeaderView.ResizeToContents,
                 DESCRIPTION: QtWidgets.QHeaderView.Stretch,
                 DEADLINE: QtWidgets.QHeaderView.ResizeToContents,
                 RISK: QtWidgets.QHeaderView.ResizeToContents,
                 ACTIVITY: QtWidgets.QHeaderView.ResizeToContents}
        for column, mode in modes.items():
            if column < self.legend_model.columnCount():
                header.setSectionResizeMode(column, mode)

    def _rebuild_views(self) -> None:
        """Reload the grid and the legend after rows were added or removed.

        Both views cache document row indexes, and an inserted or deleted line
        shifts every index after it, so both are rebuilt and refitted.
        """
        self.model.set_table(self.table)
        self.legend_model.set_table(self.table)
        self._fit_columns()
        self._fit_legend_columns()

    # -- opening -----------------------------------------------------------
    def choose(self) -> None:
        start = settings.get("table_dir") or str(Path.home())
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open a weekly table", start, "Org files (*.org);;All files (*)")
        if path:
            self.open(path)

    def open(self, path: str) -> None:
        """Load the table at ``path`` and refresh every panel."""
        try:
            table = WeeklyTable.from_file(path)
        except OSError as exc:
            self.logged.emit(f"Could not open {path}: {exc}")
            return
        self.table = table
        self.load_calendar(path)
        self.layout_notes = self._standardize_layout()
        self.model.set_table(table)
        self.legend_model.set_table(table)
        settings.put("table_dir", str(Path(path).parent))
        settings.put("table", str(Path(path)))
        self._fit_columns()
        for button in (self.save_button, self.save_as_button, self.reload_button,
                       self.project_above_button, self.project_below_button,
                       self.hour_button, self.more_button):
            button.setEnabled(True)
        self._update_insert_buttons()
        self.refresh()
        self._sync_coach_menu()
        self.block_timer.update_state()
        if settings.get("hour_view") == "true" and not self.hour_button.isChecked():
            self.hour_button.setChecked(True)
        self.logged.emit(f"Opened {path}")
        self.opened.emit(path)

    def most_recent(self) -> Optional[str]:
        """Return the table to show at startup, or ``None`` when there is none.

        The table last opened is the one wanted, because a writer works a week
        at a time. When that file has been moved or deleted, the newest org
        file in the folder of tables stands in for it, which is also the answer
        the first time the window is ever opened after a table is saved.
        """
        remembered = settings.get("table")
        if remembered and Path(remembered).is_file():
            return remembered
        folder = settings.get("table_dir")
        if not folder or not Path(folder).is_dir():
            return None
        try:
            tables = [p for p in Path(folder).glob("*.org") if p.is_file()]
        except OSError:
            return None
        if not tables:
            return None
        newest = max(tables, key=lambda p: p.stat().st_mtime)
        return str(newest)

    def open_most_recent(self) -> Optional[str]:
        """Open the table from :meth:`most_recent`.  Return what was opened.

        A failure here is not worth a dialog at startup, because the writer did
        not ask for this file. The log carries the reason and the window opens
        with an empty grid, exactly as it did before.
        """
        path = self.most_recent()
        if path is None:
            return None
        try:
            self.open(path)
        except Exception as exc:                 # pragma: no cover - defensive
            self.logged.emit(f"Could not reopen {path}: {exc}")
            return None
        return path if self.table is not None else None

    def reload(self) -> None:
        if self.table is not None and self.table.path:
            self.open(self.table.path)

    # -- inserting rows ----------------------------------------------------
    def selected_document_row(self) -> Optional[int]:
        """Return the document row under the grid's current cell, or ``None``."""
        index = self.view.currentIndex()
        if self.table is None or not index.isValid():
            return None
        if not 0 <= index.row() < self.model.rowCount():
            return None
        return self.model.document_row(index.row())

    def _on_current_changed(self) -> None:
        self._update_insert_buttons()
        self._update_time_tint()
        self._update_shift_buttons()

    def _update_time_tint(self) -> None:
        """Tint the blocks clear of the selected time, or clear the tint."""
        index = self.view.currentIndex()
        if index.isValid() and index.column() == TIME_COLUMN:
            self.model.set_time_anchor(index.row())
        else:
            self.model.set_time_anchor(None)

    def _update_insert_buttons(self) -> None:
        if self.hour_view_shown():
            return
        near = self.selected_document_row()
        ready = near is not None
        self.insert_above_button.setEnabled(ready)
        self.insert_below_button.setEnabled(ready)
        self.move_up_button.setEnabled(ready and self.table.can_move(near, True))
        self.move_down_button.setEnabled(ready and self.table.can_move(near, False))
        self.delete_row_button.setEnabled(
            ready and self.table.can_remove_block(near))

    def insert_row(self, above: bool, times: Optional[str] = None) -> Optional[int]:
        """Add an empty time block beside the selected row.

        The writer confirms the time range in a small dialog, which starts
        from a block of the same length as its neighbour placed flush against
        it. ``times`` skips the dialog. Return the document index of the new
        row, or ``None`` when nothing was inserted.
        """
        near = self.selected_document_row()
        if near is None:
            self.logged.emit("Select a row of the grid before inserting a row")
            return None
        if times is None:
            start, end = self.table.suggest_times(near, above)
            where = "above" if above else "below"
            times, accepted = QtWidgets.QInputDialog.getText(
                self, "Insert a time block",
                f"Time range of the new row {where} the selection (HH:MM-HH:MM)",
                QtWidgets.QLineEdit.Normal, f"{start}-{end}")
            if not accepted:
                return None
        start, _sep, end = (times or "").strip().partition("-")
        try:
            at = self.table.insert_block(near, above, start.strip(), end.strip())
        except ValueError as exc:
            self.logged.emit(f"Cannot insert a row: {exc}")
            QtWidgets.QMessageBox.information(self, "Insert a row", str(exc))
            return None

        column = max(self.view.currentIndex().column(), 1)
        self._rebuild_views()
        grid_row = self.model._rows.index(at)
        self.view.setCurrentIndex(self.model.index(grid_row, column))
        self._update_insert_buttons()
        start, end = self.table.rows[at].parsed
        self.logged.emit(f"Inserted an empty {start}-{end} block in "
                         f"{self.table.rows[at].section}")
        self.on_edit()
        return at

    # -- moving rows -------------------------------------------------------
    def move_row(self, up: bool) -> Optional[int]:
        """Shift the selected time block one row up or down.

        The selection follows the row, so pressing the button again keeps
        moving the same block. Return the block's new document index, or
        ``None`` when nothing moved.
        """
        near = self.selected_document_row()
        if near is None:
            self.logged.emit("Select a time block of the grid before moving a row")
            return None
        if not self.table.can_move(near, up):
            kind = self.table.rows[near].kind
            if kind == BLOCK:
                self.logged.emit("The row is already at the "
                                 + ("top" if up else "bottom") + " of the grid")
            else:
                self.logged.emit("Only a time block moves. A section header "
                                 "stays where the file puts it.")
            return None
        before = self.table.rows[near].section
        at = self.table.move_block(near, up)

        column = self.view.currentIndex().column()
        self._rebuild_views()
        grid_row = self.model._rows.index(at)
        self.view.setCurrentIndex(self.model.index(grid_row, max(column, 0)))
        self._on_current_changed()
        start, end = self.table.rows[at].parsed
        after = self.table.rows[at].section
        where = (f" into {after}" if after != before else "")
        self.logged.emit(f"Moved the {start}-{end} block "
                         + ("up" if up else "down") + where)
        self.on_edit()
        return at

    # -- deleting rows -----------------------------------------------------
    def _confirm(self, title: str, text: str) -> bool:
        """Ask a yes-or-no question.  Return whether the writer said yes."""
        answer = QtWidgets.QMessageBox.question(
            self, title, text,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No)
        return answer == QtWidgets.QMessageBox.Yes

    def delete_row(self, confirm: bool = True) -> Optional[int]:
        """Delete the selected time block.  Return the index it held.

        A row that still holds project codes is deleted only after the writer
        confirms, because there is no undo short of Reload. An empty row goes
        at once. The selection moves to the grid row that took its place, or
        to the row above when the last row went. ``confirm`` of ``False`` skips
        the question. Return ``None`` when nothing was deleted.
        """
        near = self.selected_document_row()
        if near is None:
            self.logged.emit("Select a time block of the grid before deleting a row")
            return None
        if not self.table.can_remove_block(near):
            self.logged.emit("Only a time block is deleted. A section header "
                             "stays where the file puts it.")
            return None
        row = self.table.rows[near]
        start, end = row.parsed
        filled = [self.table.cell(near, index)
                  for index, _offset, _label in self.table.columns
                  if self.table.cell(near, index)]
        if filled and confirm and not self._confirm(
                "Delete a row",
                f"The {start}-{end} block holds {len(filled)} project "
                f"code(s): {' '.join(filled)}.\n\nDelete the row?"):
            return None
        grid_row = self.view.currentIndex().row()
        column = self.view.currentIndex().column()
        section = row.section
        self.table.remove_block(near)

        self._rebuild_views()
        count = self.model.rowCount()
        if count:
            self.view.setCurrentIndex(
                self.model.index(min(grid_row, count - 1), max(column, 0)))
        self._on_current_changed()
        self.logged.emit(f"Deleted the {start}-{end} block from {section}")
        self.on_grid_edit()                         # the legend may owe a row less
        return near

    def delete_project(self, confirm: bool = True) -> Optional[int]:
        """Delete the selected legend entry.  Return the index it held.

        A project the grid still uses is deleted only after the writer
        confirms, because its cells then show as not in the key. The selection
        moves to the entry that took its place, or to the one above when the
        last entry went. ``confirm`` of ``False`` skips the question. Return
        ``None`` when nothing was deleted.
        """
        near = self.selected_legend_row()
        if near is None:
            self.logged.emit("Select a project in the legend before deleting it")
            return None
        code = self.table.rows[near].parsed[0]
        used = self.table.cells_using(code)
        if used and confirm and not self._confirm(
                "Delete a project",
                f"{used} cell(s) of the grid use {code}. They will show as not "
                f"in the key.\n\nDelete {code} from the legend?"):
            return None
        legend_row = self.legend_view.currentIndex().row()
        column = self.legend_view.currentIndex().column()
        self.table.remove_legend(near)

        if near <= max(self.model._rows, default=-1):
            self.model.set_table(self.table)    # a grid row moved up
            self._fit_columns()
        self.legend_model.set_table(self.table)
        self._fit_legend_columns()
        count = self.legend_model.rowCount()
        if count:
            self.legend_view.setCurrentIndex(
                self.legend_model.index(min(legend_row, count - 1), max(column, 0)))
        self._update_project_move_buttons()
        self.logged.emit(f"Deleted project {code} from the legend"
                         + (f"; {used} cell(s) still use it" if used else ""))
        self.on_edit()
        return near

    # -- inserting projects ------------------------------------------------
    def selected_legend_row(self) -> Optional[int]:
        """Return the document row of the selected legend entry, or ``None``."""
        index = self.legend_view.currentIndex()
        if self.table is None or not index.isValid():
            return None
        if not 0 <= index.row() < self.legend_model.rowCount():
            return None
        return self.legend_model.document_row(index.row())

    def _ask_project(self, code: str):
        """Ask for a code, description, and risk tag.  Return them, or ``None``."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Insert a project")
        form = QtWidgets.QFormLayout(dialog)
        code_edit = QtWidgets.QLineEdit(code)
        code_edit.setMaxLength(4)
        description_edit = QtWidgets.QLineEdit()
        description_edit.setPlaceholderText("e.g. 0201dusp1")
        deadline_edit = QtWidgets.QLineEdit()
        deadline_edit.setPlaceholderText("YYYY-MM-DD, or leave empty")
        risk_box = QtWidgets.QComboBox()
        risk_box.addItems([label for label, _class in RISK_CHOICES])
        activity_box = QtWidgets.QComboBox()
        activity_box.addItems([label for label, _a in ACTIVITY_CHOICES])
        activity_box.setToolTip(
            "The activity a bare code takes, so email can always count as "
            "support. A letter in a cell, such as eA, still wins.")
        form.addRow("Code", code_edit)
        form.addRow("Project", description_edit)
        form.addRow("Deadline", deadline_edit)
        form.addRow("Risk tag", risk_box)
        form.addRow("Default activity", activity_box)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        description_edit.setFocus()
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None
        risk = dict(RISK_CHOICES).get(risk_box.currentText())
        activity = dict(ACTIVITY_CHOICES).get(activity_box.currentText())
        deadline = deadline_edit.text().strip()
        if not namemod.valid_deadline(deadline):
            self.logged.emit(f"Ignored the deadline {deadline!r}: write it as YYYY-MM-DD")
            deadline = ""
        description = namemod.join_deadline(description_edit.text(), deadline)
        return code_edit.text(), description, risk, activity

    def insert_project(self, above: bool, code: Optional[str] = None,
                       description: str = "",
                       risk: Optional[str] = None,
                       activity: Optional[str] = None) -> Optional[int]:
        """Add a legend entry beside the selected one.  Return its document row.

        With no entry selected, a project inserted below goes to the end of the
        legend and one inserted above goes to the start. ``code`` skips the
        dialog, which otherwise offers the first code not yet in use, a
        single letter while one is free and then ``AA``, ``AB``, and so on.
        """
        if self.table is None:
            return None
        near = self.selected_legend_row()
        if near is None:
            rows = self.table.legend_rows()
            near = rows[0] if (above and rows) else None
        if code is None:
            answer = self._ask_project(self.table.next_free_code())
            if answer is None:
                return None
            code, description, risk, *rest = answer
            activity = rest[0] if rest else None
        try:
            at = self.table.insert_legend(near, above, code, description, risk,
                                          activity)
        except ValueError as exc:
            self.logged.emit(f"Cannot insert a project: {exc}")
            QtWidgets.QMessageBox.information(self, "Insert a project", str(exc))
            return None

        if at <= max(self.model._rows, default=-1):
            self.model.set_table(self.table)    # a grid row moved down
        self.legend_model.set_table(self.table)
        self._fit_legend_columns()
        legend_row = self.legend_model._rows.index(at)
        self.legend_view.setCurrentIndex(
            self.legend_model.index(legend_row, DESCRIPTION))
        self.logged.emit(f"Inserted project {self.table.rows[at].parsed[0]} "
                         "in the legend")
        self.on_edit()
        return at

    # -- moving projects ---------------------------------------------------
    def _update_project_move_buttons(self) -> None:
        near = self.selected_legend_row()
        ready = near is not None
        self.project_up_button.setEnabled(
            ready and self.table.can_move_legend(near, True))
        self.project_down_button.setEnabled(
            ready and self.table.can_move_legend(near, False))
        self.delete_project_button.setEnabled(ready)

    def move_project(self, up: bool) -> Optional[int]:
        """Shift the selected legend entry one row up or down.

        The selection follows the entry, so pressing the button again keeps
        moving the same project. Return its new document index, or ``None``
        when nothing moved.
        """
        near = self.selected_legend_row()
        if near is None:
            self.logged.emit("Select a project in the legend before moving it")
            return None
        if not self.table.can_move_legend(near, up):
            self.logged.emit("The project is already at the "
                             + ("top" if up else "bottom") + " of the legend")
            return None
        code = self.table.rows[near].parsed[0]
        at = self.table.move_legend(near, up)

        column = self.legend_view.currentIndex().column()
        if min(at, near) <= max(self.model._rows, default=-1):
            self.model.set_table(self.table)    # a grid row moved
            self._fit_columns()
        self.legend_model.set_table(self.table)
        self._fit_legend_columns()
        legend_row = self.legend_model._rows.index(at)
        self.legend_view.setCurrentIndex(
            self.legend_model.index(legend_row, max(column, 0)))
        self._update_project_move_buttons()
        self.logged.emit(f"Moved project {code} "
                         + ("up" if up else "down") + " in the legend")
        self.on_edit()
        return at

    # -- moving the activity into the cells --------------------------------
    def move_activities_into_cells(self, delete_sections: Optional[bool] = None
                                   ) -> Optional[int]:
        """Write each section's activity letter into the bare cells under it.

        A cell such as ``A`` under Rewriting becomes ``eA``. A cell that has a
        letter already, or whose project names a default activity, is left as
        it is. The writer is then asked whether to delete the section rows,
        which no longer decide anything. ``delete_sections`` answers that
        question in advance. Return the number of cells changed, or ``None``
        when there is no table.
        """
        if self.table is None:
            return None
        changed = self.table.move_activities_into_cells()
        has_sections = any(row.kind == SECTION for row in self.table.rows)
        if delete_sections is None and has_sections:
            answer = QtWidgets.QMessageBox.question(
                self, "Move activities into cells",
                f"{changed} cell(s) now carry their activity letter.\n\n"
                "Delete the section rows too? Every block keeps its activity.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No)
            delete_sections = answer == QtWidgets.QMessageBox.Yes
        removed = self.table.remove_section_rows() if delete_sections else 0
        self._rebuild_views()
        self._update_insert_buttons()
        self.logged.emit(f"Moved the activity into {changed} cell(s)"
                         + (f" and deleted {removed} section row(s)" if removed else ""))
        self.on_edit()
        return changed

    # -- project and deadline ----------------------------------------------
    def tidy_legend(self, confirm: Optional[bool] = None, reference=None
                    ) -> Optional[int]:
        """Split each legend description into a project and a deadline.

        The changes are listed first, including any text the split would drop,
        so the writer decides with the whole picture. ``confirm`` answers that
        question in advance. Return the number of rows rewritten, or ``None``
        when there is no table or the writer declines.
        """
        if self.table is None:
            return None
        if reference is None:
            import datetime as _dt
            week = settings.get("week")
            try:
                reference = _dt.date.fromisoformat(week) if week else _dt.date.today()
            except ValueError:
                reference = _dt.date.today()
        changes = self.table.tidy_legend(reference)
        if not changes:
            self.logged.emit("Every legend entry is already a project and a deadline")
            return 0
        if confirm is None:
            lines = []
            for _row, code, old, project, deadline, dropped in changes:
                lines.append(f"{code}: {old}")
                lines.append(f"   project  {project}")
                lines.append(f"   deadline {deadline or '(none)'}")
                if dropped:
                    lines.append(f"   dropped  {dropped}")
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Split legend into project and deadline")
            box.setText(f"{len(changes)} legend entr{'y' if len(changes) == 1 else 'ies'} "
                        "will change. Open Show Details to read each one, "
                        "including any text that would be dropped. The file "
                        "changes only when you save.")
            box.setDetailedText("\n".join(lines))
            box.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
            confirm = box.exec_() == QtWidgets.QMessageBox.Ok
        if not confirm:
            return None
        self.table.tidy_legend(reference, apply=True)
        self.legend_model.set_table(self.table)
        self._fit_legend_columns()
        dropped = [f"{c[1]}: {c[5]}" for c in changes if c[5]]
        self.logged.emit(f"Split {len(changes)} legend entr"
                         f"{'y' if len(changes) == 1 else 'ies'} into project and deadline")
        for line in dropped:
            self.logged.emit(f"  dropped from {line}")
        self.on_edit()
        return len(changes)

    # -- the external editor -----------------------------------------------
    def _ask_save_before_editing(self) -> str:
        """Return ``save``, ``saved``, or ``cancel`` for a table with unsaved edits."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("Unsaved edits")
        box.setText("The grid holds edits that are not in the file yet. "
                    "The editor will read the file.")
        save = box.addButton("Save and open", QtWidgets.QMessageBox.AcceptRole)
        stale = box.addButton("Open the saved version",
                              QtWidgets.QMessageBox.DestructiveRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is save:
            return "save"
        if clicked is stale:
            return "saved"
        return "cancel"

    def open_externally(self) -> Optional[list]:
        """Open the table file in the writer's editor.  Return the command run."""
        if self.table is None or not self.table.path:
            self.logged.emit("Save the table to a file before opening it in an editor")
            return None
        if self.table.dirty:
            choice = self._ask_save_before_editing()
            if choice == "cancel":
                return None
            if choice == "save" and self.save() is None:
                return None
        try:
            argv, source = self.launch_editor(self.table.path)
        except OSError as exc:
            self.logged.emit(f"Could not start the editor: {exc}")
            QtWidgets.QMessageBox.warning(
                self, "Open in editor",
                f"Could not start the editor.\n\n{exc}\n\nSet WHGEDITOR in "
                f"~/.bashrc to a full path, such as\n"
                f'export WHGEDITOR="/opt/homebrew/bin/emacsclient -n"')
            return None
        self.logged.emit(f"Opened {self.table.path} with {' '.join(argv)} "
                         f"(editor from {source}). Press Reload after saving there.")
        return argv

    def on_edit(self) -> None:
        """Refresh the readings after an edit reaches the document."""
        self.refresh()
        if hasattr(self, "block_timer"):
            self.block_timer.update_state()
        self.edited.emit()

    def on_grid_edit(self) -> None:
        """A cell changed, so the legend may owe the grid a row.

        Only a grid edit syncs. A legend edit does not, because renaming a code
        there would otherwise remove the row being renamed and add back the one
        it replaced, and the writer would watch their edit bounce.
        """
        if self.table is not None and self.table.sync_legend():
            self.legend_model.set_table(self.table)
            self._fit_legend_columns()
        self.on_edit()

    # -- reading files in other layouts --------------------------------------
    def _standardize_layout(self) -> list:
        """Bring the open table to the standard layout, and say what changed.

        The table has already moved a legend kept in its own ``This week``
        table back into the week. Here the lists named by their tab titles,
        such as ``Fall 2026 projects``, get their standard names, which the
        calendar makes possible, and a list named twice is merged. The file
        is marked changed, so a save writes the standard layout; nothing is
        written until then.
        """
        from ..project_lists import normalize_title
        table = self.table
        notes = list(getattr(table, "layout_notes", []))
        titles, _tips = self.list_titles()
        mapping = {normalize_title(title): name for name, title in titles.items()}
        if self.calendar is not None:
            earlier = [p for p in self.calendar.of_kind(self.period_kind())]
            for period in earlier:
                mapping.setdefault(normalize_title(f"Carried over from {period.name}"),
                                   CARRIED)
                mapping.setdefault(normalize_title(f"Completed in {period.name}"),
                                   "completed-this-semester")
        renamed = table.lists.tidy_names(mapping)
        if renamed:
            table.dirty = True
            notes += renamed
        aligned = table.lists.align_tasks()
        if aligned:
            table.dirty = True
            notes += aligned
        blocks = table.legend_blocks()
        if len(blocks) > 1:
            notes.append(
                f"The legend holds {len(blocks)} blocks separated by rules, "
                f"{sum(len(b) for b in blocks)} rows in all, as in the older layout "
                "that kept the semester lists inside the legend. More > Move extra "
                "legend blocks into the lists moves all but the first block to "
                "the lists.")
        self._show_layout_notes(notes)
        for note in notes:
            self.logged.emit(note)
        return notes

    def _show_layout_notes(self, notes) -> None:
        if not notes:
            self.layout_banner.setVisible(False)
            return
        changed = self.table is not None and self.table.dirty
        tail = ("<br><i>Save to keep these changes; the file on disk is not "
                "touched until then.</i>" if changed else "")
        self.layout_banner.setText(
            "<b>This file was read with changes:</b><br>"
            + "<br>".join(f"• {n}" for n in notes) + tail)
        self.layout_banner.setVisible(True)

    def split_legend_blocks(self, confirm: bool = True):
        """Move the legend blocks after the first into the semester lists."""
        from ..project_lists import HORIZONS
        if self.table is None:
            return None
        blocks = self.table.legend_blocks()
        if len(blocks) < 2:
            self.logged.emit("The legend has one block, so there is nothing to move")
            return None
        titles, _tips = self.list_titles()
        lines = [f"Keep the first block ({len(blocks[0])} projects) as this week's legend."]
        for target, block in zip(HORIZONS, blocks[1:]):
            lines.append(f"Move block {blocks.index(block) + 1} "
                         f"({len(block)} projects) to {titles[target]}.")
        if len(blocks) - 1 > len(HORIZONS):
            lines.append(f"There are only {len(HORIZONS)} lists, so this cannot run.")
        if confirm and not self._confirm(
                "Move legend blocks", "\n".join(lines)
                + "\n\nA project already on a list is not added twice. The file "
                "is written when you save."):
            return None
        try:
            moved = self.table.split_legend_blocks()
        except ValueError as exc:
            self.logged.emit(f"Could not move the blocks: {exc}")
            return None
        self._rebuild_views()
        for panel in self.list_panels.values():
            panel.set_table(self.table)
        self.layout_banner.setVisible(False)
        for target, added in moved:
            self.logged.emit(f"Moved {added} project(s) to {titles[target]}")
        self.on_grid_edit()
        return moved

    # -- planning periods -------------------------------------------------
    def load_calendar(self, table_path: Optional[str] = None) -> None:
        """Read the calendar for the open table, or forget it when there is none."""
        path = periodsmod.calendar_path(
            table_path or (self.table.path if self.table else None),
            settings.get("periods_file"))
        self.calendar_file = path
        self.calendar = None
        if path is not None and path.is_file():
            try:
                self.calendar = periodsmod.Calendar.from_file(str(path))
            except (OSError, UnicodeDecodeError) as exc:
                self.logged.emit(f"Could not read {path}: {exc}")

    def period_kind(self) -> str:
        return settings.get("period_kind") or periodsmod.DEFAULT_KIND

    def reference_date(self) -> _dt.date:
        """Return the Monday the open file is named for, else today."""
        today = self.today()
        if self.table is not None and self.table.path:
            named = periodsmod.week_date(Path(self.table.path).stem, today)
            if named is not None:
                return named
        return today

    def _week_tips(self) -> dict:
        """Return a tooltip for each week list naming the week it stands for."""
        monday = self.week_monday() if self.table is not None else None
        tips = {}
        for n, name in enumerate(WEEKS, start=1):
            when = ""
            if monday is not None:
                first = monday + _dt.timedelta(weeks=n)
                last = first + _dt.timedelta(days=6)
                when = f"The week of {first:%B} {first.day} to {last:%B} {last.day}. "
            tips[name] = (f"{when}Projects waiting for that week. Select one and "
                          "press Copy to this week's legend to work on it this week.")
        return tips

    def current_period(self):
        if self.calendar is None:
            return None
        return self.calendar.current(self.period_kind(), self.reference_date())

    def list_titles(self):
        """Return ``({list: title}, {list: tooltip})`` from the calendar."""
        if self.calendar is None:
            return dict(LISTS), self._week_tips()
        # Until the lists are rolled forward, they still belong to the period
        # they are filed under, so the titles follow that period.
        anchor = self.reference_date()
        now = self.current_period()
        filed = self.table.lists.period() if self.table is not None else None
        filed_period = self.calendar.find(self.period_kind(), filed) if filed else None
        if filed_period is not None and now is not None and filed_period.start < now.start:
            anchor = filed_period.start
        ahead = self.calendar.ahead(self.period_kind(), anchor, len(HORIZONS))
        titles = list_titles(ahead)
        tips = {}
        for name, period in zip(HORIZONS, ahead):
            if period is not None:
                tips[name] = (f"{period.name}: {period.start} to {period.end}. "
                              f"Kept in the file as {name}.")
        if ahead and ahead[0] is not None:
            tips["completed-this-semester"] = (
                f"Projects finished in {ahead[0].name}. Kept in the file as "
                "completed-this-semester.")
            earlier = [p for p in self.calendar.of_kind(self.period_kind())
                       if p.start < ahead[0].start and p.horizon]
            if earlier:
                titles[CARRIED] = f"Carried over from {earlier[-1].name}"
        tips[CARRIED] = ("Projects left on the current list at the last roll "
                         "forward. Move each to the current list or delete it.")
        tips.update(self._week_tips())
        return titles, tips

    def update_period_banner(self) -> None:
        """Show what the lists need: a period to file under, or a roll forward."""
        self.period_banner.setVisible(False)
        if self.table is None or self.calendar is None:
            return
        now = self.current_period()
        if now is None:
            return
        filed = self.table.lists.period()
        kind = self.period_kind()
        if filed is None:
            self.period_label.setText("Which period are these project lists for?")
            self.period_choice.clear()
            names = [p.name for p in self.calendar.of_kind(kind)]
            self.period_choice.addItems(names)
            self.period_choice.setCurrentText(now.name)
            for widget, on in ((self.period_choice, True),
                               (self.period_file_button, True),
                               (self.roll_button, False)):
                widget.setVisible(on)
            self.period_banner.setVisible(True)
            return
        steps = self.calendar.steps_between(kind, filed, now.name)
        if self.calendar.find(kind, filed) is None:
            self.period_label.setText(
                f"The lists are filed under {filed}, which is not in "
                f"{self.calendar_file.name}.")
            for widget in (self.period_choice, self.period_file_button,
                           self.roll_button):
                widget.setVisible(False)
            self.period_banner.setVisible(True)
            return
        if not steps:
            return
        self.period_label.setText(
            f"The lists are filed under {filed}, and this week falls in "
            f"{now.name}.")
        self.roll_button.setText(f"Roll forward to {now.name}")
        self.period_choice.setVisible(False)
        self.period_file_button.setVisible(False)
        self.roll_button.setVisible(True)
        self.period_banner.setVisible(True)

    def file_lists_under(self, period: str) -> bool:
        """Record the period the lists belong to, without moving any project."""
        if self.table is None or not period:
            return False
        changed = self.table.lists.set_period(period)
        if changed:
            self.table.dirty = True
            self.logged.emit(f"Filed the project lists under {period}")
            self._title_lists()
            self.on_edit()
        return changed

    def roll_steps(self):
        """Return the periods a roll forward passes through, nearest first."""
        now = self.current_period()
        filed = self.table.lists.period() if self.table else None
        if now is None or filed is None:
            return []
        kind = self.period_kind()
        start = self.calendar.find(kind, filed)
        if start is None:
            return []
        return [p for p in self.calendar.of_kind(kind)
                if start.start < p.start <= now.start and p.horizon]

    def roll_forward(self, confirm: bool = True) -> int:
        """Move the lists forward to the current period.  Return the steps taken."""
        steps = self.roll_steps()
        if not steps:
            return 0
        lists = self.table.lists
        filed = lists.period()
        completed = len(lists.entries("completed-this-semester"))
        current = len(lists.entries(HORIZONS[0]))
        archive = periodsmod.archive_path(self.calendar_file)
        text = (f"Roll the project lists forward from {filed} to "
                f"{steps[-1].name}"
                + (f", {len(steps)} periods" if len(steps) > 1 else "") + "?\n\n"
                f"- {completed} completed project(s) go to {archive}\n"
                f"- {current} project(s) on the current list go to Carried over, "
                "for you to keep or delete\n"
                "- each later list moves one period nearer\n\n"
                "The weekly grid and the legend do not change. The table is "
                "written when you save.")
        if confirm and not self._confirm("Roll forward", text):
            return 0
        previous = filed
        for period in steps:
            result = lists.roll_forward(period.name)
            if result.completed:
                added = periodsmod.archive_completed(
                    archive, previous, [e.text() for e in result.completed])
                self.logged.emit(f"Filed {added} completed project(s) of "
                                 f"{previous} in {archive}")
            previous = period.name
        self.table.dirty = True
        for panel in self.list_panels.values():
            panel.set_table(self.table)
        self._title_lists()
        self.logged.emit(f"Rolled the project lists forward to {steps[-1].name}")
        self.on_edit()
        if self.list_panels[CARRIED].model.rowCount():
            self.show_list(CARRIED)
            self.logged.emit("Press Triage on the Carried over tab for a suggested "
                             "keep, defer, or drop for each carried project")
        return len(steps)

    def open_periods(self) -> Optional[str]:
        """Edit the calendar.  Return the file written, or ``None``."""
        path = self.calendar_file or periodsmod.calendar_path(
            None, settings.get("periods_file")) or (
            Path(settings.get("table_dir") or Path.home()) / periodsmod.FILE_NAME)
        calendar = self.calendar or periodsmod.Calendar([], str(path))
        dialog = PeriodsDialog(calendar, path, self.period_kind(), parent=self)
        if not self.run_periods(dialog):
            return None
        settings.put("period_kind", dialog.kind())
        self.calendar, self.calendar_file = calendar, Path(path)
        self.logged.emit(f"Saved the planning periods to {path}")
        self._title_lists()
        self.update_period_banner()
        return str(path)

    # -- the hour view -----------------------------------------------------
    def _fit_hour_columns(self) -> None:
        header = self.hour_view.horizontalHeader()
        header.setStretchLastSection(False)
        columns = self.hour_model.columnCount()
        if not columns:
            return
        header.setSectionResizeMode(HOUR_COLUMN, QtWidgets.QHeaderView.ResizeToContents)
        for column in range(1, columns):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.Stretch)

    def hour_view_shown(self) -> bool:
        stack = getattr(self, "grid_stack", None)
        return stack is not None and stack.currentWidget() is self.hour_view

    def set_hour_view(self, on: bool) -> None:
        """Show the 24-row hour view, or the row view when ``on`` is false.

        The row buttons act on a selected file row, which the hour view does
        not have, so they are disabled while it shows.
        """
        if self.hour_button.isChecked() != bool(on):
            self.hour_button.setChecked(bool(on))       # calls back here
            return
        self.grid_stack.setCurrentWidget(self.hour_view if on else self.view)
        settings.put("hour_view", "true" if on else "false")
        if on:
            for button in (self.insert_above_button, self.insert_below_button,
                           self.move_up_button, self.move_down_button,
                           self.delete_row_button):
                button.setEnabled(False)
            self._fit_hour_columns()
        elif self.table is not None:
            self._on_current_changed()
        self._update_shift_buttons()

    def open_picker(self, index=None) -> Optional[tuple]:
        """Open the range picker for a cell of the hour view.

        Return the ``(start, end, value)`` placed, ``("remove", row, column)``
        when a block was removed, or ``None`` when nothing changed.
        """
        if self.table is None or index is None or not index.isValid():
            return None
        if index.column() == HOUR_COLUMN:
            return None
        hour = index.row()
        offset = self.hour_model.offset(index.column())
        label = self.table.day_labels[index.column() - 1]
        starts = self.hour_model.blocks_at(hour, index.column())
        dialog = HourPicker(self.table, offset, label, hour, existing=starts,
                            parent=self, monday=self.week_monday(),
                            review_blocks=starts + self.hour_model.spans_at(
                                hour, index.column()))
        if dialog.review_panel is not None:
            dialog.review_panel.table_edited.connect(self._on_review_table_edit)
            dialog.review_panel.logged.connect(self.logged)
        removed = []
        dialog.remove_requested.connect(lambda r, c: removed.append((r, c)))
        if not self.run_picker(dialog):
            return None
        if removed:
            row, column = removed[0]
            self.clear_block(row, column)
            return ("remove", row, column)
        if dialog.choice is None:
            return None
        start, end, value = dialog.choice
        self.place_block(offset, start, end, value, push=dialog.push())
        self.hour_view.setCurrentIndex(index)
        return dialog.choice

    def place_block(self, offset: int, start: str, end: str, value: str,
                    push: bool = False) -> Optional[int]:
        """Write a block for one day and range.  Return its document row.

        With ``push``, later blocks that day that the new block overlaps move
        down first, so they keep their length and order.
        """
        try:
            pushed = self.table.plan_push(offset, start, end) if push else []
            row, inserted = self.table.place_block(offset, start, end, value,
                                                   push=push)
        except ValueError as exc:
            self.logged.emit(f"Could not place the block: {exc}")
            return None
        if pushed:
            self._rekey(pushed)
            self.logged.emit("Pushed down " + ", ".join(
                f"{b.letter} to {s}-{e}" for b, s, e in pushed))
            inserted = True
        if inserted:
            self._rebuild_views()
            self.logged.emit(f"Added the {start}-{end} row and placed {value}")
        else:
            self.logged.emit(f"Placed {value} at {start}-{end}")
        self.on_grid_edit()
        return row

    def clear_block(self, row: int, column: int) -> bool:
        """Empty one cell and keep its row."""
        start, end = self.table.rows[row].parsed
        value = self.table.cell(row, column)
        changed = self.table.clear_block(row, column)
        if changed:
            self.logged.emit(f"Removed {value} from {start}-{end}; the row stays")
            self.on_grid_edit()
        return changed

    # -- shifting a block in time ------------------------------------------
    def selected_block(self):
        """Return the block under the current cell of the shown view, or ``None``.

        In the hour view this is the first block that starts in the hour, or,
        in an hour a longer block runs into, that block. In the row view it is
        the block in the current cell.
        """
        if self.table is None:
            return None
        if self.hour_view_shown():
            index = self.hour_view.currentIndex()
            if not index.isValid() or index.column() == HOUR_COLUMN:
                return None
            blocks = (self.hour_model.blocks_at(index.row(), index.column())
                      or self.hour_model.spans_at(index.row(), index.column()))
            return blocks[0] if blocks else None
        index = self.view.currentIndex()
        if not index.isValid() or index.column() == TIME_COLUMN:
            return None
        if not 0 <= index.row() < self.model.rowCount():
            return None
        row = self.model.document_row(index.row())
        if self.table.rows[row].kind != BLOCK:
            return None
        return self.table.block_at(row, self.model.document_cell(index.row(),
                                                                 index.column()))

    def _update_shift_buttons(self) -> None:
        ready = self.selected_block() is not None
        for button in getattr(self, "shift_buttons", {}).values():
            button.setEnabled(ready)
        if hasattr(self, "review_button"):
            self.review_button.setEnabled(ready)
        panel = getattr(self, "list_panels", {}).get(GRASSCATCHER)
        if panel is not None and panel.commit_button is not None:
            panel.commit_button.setToolTip(
                "Make the selected task an objective of the block selected in "
                "the grid, and take it off the grasscatcher"
                + ("" if ready else ". Select a block in the grid first."))

    def pomodoro_block(self):
        """Return the block whose length sets the Pomodoro cycle, or ``None``.

        That is the block under way when there is one, and otherwise the
        block selected in the grid.
        """
        if self.table is None:
            return None
        state = self.block_timer.update_state()
        if state.kind in ("live", "ending"):
            return state.block
        return self.selected_block()

    def select_block(self, block) -> None:
        """Select ``block`` in the shown view, scrolled into sight."""
        if self.table is None or block is None:
            return
        grid_column = [c for c, _o, _l in self.table.columns].index(block.column) + 1
        if self.hour_view_shown():
            index = self.hour_model.index(int(block.start[:2]), grid_column)
            self.hour_view.setCurrentIndex(index)
            self.hour_view.scrollTo(index)
        else:
            index = self.model.index(self.model._rows.index(block.row), grid_column)
            self.view.setCurrentIndex(index)
            self.view.scrollTo(index)

    # -- objectives and reviews -----------------------------------------------
    def _sync_coach_menu(self) -> None:
        if hasattr(self, "ai_off_action"):
            off = settings.get("ai_off_week") == coachmod.monday_of(self.today()).isoformat()
            self.ai_off_action.blockSignals(True)
            self.ai_off_action.setChecked(off)
            self.ai_off_action.blockSignals(False)

    def week_monday(self) -> Optional[_dt.date]:
        """Return the Monday of the open table's week, or ``None``.

        A dated file name such as ``Oct12`` gives the week directly. A file
        renamed to its canonical name carries no date, so the week plan import
        filed it under is looked up in the habit database, and failing that
        the week last worked on in the command forms is used.
        """
        if self.table is None or not self.table.path:
            return None
        named = periodsmod.week_date(Path(self.table.path).stem, self.today())
        if named is not None:
            return named - _dt.timedelta(days=named.weekday())
        path = settings.get("db")
        if path and Path(path).is_file():
            try:
                con = dbmod.connect(path)
                try:
                    row = con.execute(
                        "SELECT week_start FROM plan_week WHERE table_path = ?"
                        " ORDER BY week_start DESC LIMIT 1",
                        (str(self.table.path),)).fetchone()
                finally:
                    con.close()
                if row is not None:
                    return _dt.date.fromisoformat(row[0])
            except Exception:                             # pragma: no cover
                pass
        week = settings.get("week")
        try:
            day = _dt.date.fromisoformat(week) if week else None
        except ValueError:
            day = None
        return None if day is None else day - _dt.timedelta(days=day.weekday())

    def _block_key(self, block, start: Optional[str] = None):
        monday = self.week_monday()
        if monday is None:
            return None
        key = reviewmod.BlockKey.for_block(monday, block)
        return key if start is None else reviewmod.BlockKey(key.day, start, key.code)

    def _rekey(self, moves) -> None:
        """Carry the objectives and reviews of moved blocks to their new starts."""
        path = settings.get("db")
        if not path or not moves or self.week_monday() is None:
            return
        try:
            con = dbmod.connect(path)
            try:
                reviewmod.ensure(con)
                for block, start, _end in moves:
                    reviewmod.rekey(con, self._block_key(block),
                                    self._block_key(block, start))
            finally:
                con.close()
        except Exception as exc:                         # pragma: no cover
            self.logged.emit(f"Could not move the reviews with the blocks: {exc}")

    # -- syncing the grasscatcher with the project logs ---------------------
    def projects_root(self) -> Path:
        return Path(settings.get("projects_root") or Path.home()).expanduser()

    def plan_todo_sync(self):
        """Return one :class:`~writing_habit.todo_sync.ProjectSync` per legend project."""
        from .. import todo_sync
        rows = todo_sync.grasscatcher_rows(self.table.lists)
        plans = []
        for code in self.table.legend():
            info = self.table.project_info(code) or {}
            project = (info.get("name") or "").strip()
            if todo_sync.project_number(project) is None:
                continue
            log, candidates = todo_sync.find_log(project, self.projects_root())
            plans.append(todo_sync.plan_project(code, project, log, rows, candidates))
        return plans

    def _todo_sync_text(self, plans) -> str:
        lines = []
        for plan in plans:
            head = f"{plan.code}: {plan.project}"
            if plan.problem:
                lines.append(f"{head}: {plan.problem}")
                continue
            if not plan.changes:
                lines.append(f"{head}: up to date")
                continue
            lines.append(f"{head} ({plan.log})")
            lines += [f"    to the grasscatcher: {t}" for t in plan.to_grasscatcher]
            lines += [f"    to the log as TODO: {t}" for t in plan.to_log]
            lines += [f"    done in the log, off the grasscatcher: "
                      f"{self.table.lists.entries(GRASSCATCHER)[p].description}"
                      for p in plan.done]
            lines += [f"    priority from the log: {t}" for _p, t in plan.reprioritize]
            if plan.lock is not None and plan.to_log:
                lines.append(f"    WARNING: {plan.lock.name} shows the log is open in "
                             "Emacs; revert that buffer after the sync")
        return "\n".join(lines)

    def sync_todos(self, confirm: bool = True) -> Optional[dict]:
        """Bring the grasscatcher and the logs' Project TODOS up to date.

        The changes are shown first. The grasscatcher changes reach the file
        when you save; the logs are written at once, each with a ``~`` copy.
        Return ``{"grasscatcher": n, "logs": n}``, or ``None`` when nothing ran.
        """
        from .. import todo_sync
        if self.table is None:
            return None
        plans = self.plan_todo_sync()
        if not plans:
            self.logged.emit("No project in this week's legend starts with a "
                             "four-digit number, so no log was looked for")
            return None
        text = self._todo_sync_text(plans)
        if not any(p.changes for p in plans):
            self.logged.emit("The grasscatcher and the logs agree\n" + text)
            return {"grasscatcher": 0, "logs": 0}
        if confirm and not self._confirm(
                "Sync to-dos", "Make these changes?\n\n" + text
                + "\n\nThe logs are written now, each with a ~ copy. The "
                "grasscatcher is written when you save the table."):
            return None
        changed = todo_sync.apply_to_lists(self.table.lists, plans)
        written = 0
        for plan in plans:
            if plan.log is not None and plan.to_log:
                written += todo_sync.write_log(plan.log, plan.to_log)
                self.logged.emit(f"Added {len(plan.to_log)} to-do(s) to {plan.log}")
        if changed:
            self.table.dirty = True
            self._reload_list(GRASSCATCHER)
            self.on_edit()
        self.logged.emit(f"Synced to-dos: {changed} grasscatcher change(s), "
                         f"{written} new log to-do(s)")
        return {"grasscatcher": changed, "logs": written}

    def _reload_list(self, name: str) -> None:
        """Redraw one list after a change made outside its own panel.

        A list panel's view counts its rows when its model is reset, and
        :meth:`_refresh_lists` resets a panel only when the table changes, so
        rows the review panel or the coach added would stay out of sight.
        """
        panel = self.list_panels.get(name)
        if panel is not None:
            panel.set_table(self.table)
        self._title_lists()

    def _on_review_table_edit(self) -> None:
        self._reload_list(GRASSCATCHER)
        self.on_edit()

    def open_review(self, block=None):
        """Open the objectives and review of ``block``, or of the selected one."""
        block = block or self.selected_block()
        if block is None:
            self.logged.emit("Select a block before reviewing it")
            return None
        dialog = ReviewDialog(self.table, self.week_monday(), [block], parent=self)
        dialog.panel.table_edited.connect(self._on_review_table_edit)
        dialog.panel.logged.connect(self.logged)
        self.run_review(dialog)
        return dialog

    # -- the coach -------------------------------------------------------------
    def set_ai_off(self, on: bool) -> None:
        """Mark the calendar week of today as a week without the coach, or clear it."""
        monday = coachmod.monday_of(self.today())
        settings.put("ai_off_week", monday.isoformat() if on else "")
        self.logged.emit("The coach is off for the week of "
                         f"{monday.isoformat()}" if on else "The coach is back on")

    def open_coach_settings(self):
        """Open the Coach settings dialog with the server's models listed."""
        from .coach_settings import CoachSettingsDialog
        dialog = CoachSettingsDialog(self)
        dialog.lister = self.list_models
        dialog.refresh()
        saved = self.run_coach_settings(dialog)
        if saved:
            self.model_action.blockSignals(True)
            self.model_action.setChecked(settings.get("ai_debrief") == "true")
            self.model_action.blockSignals(False)
            state = "on" if settings.get("ai_debrief") == "true" else "off"
            self.logged.emit(f"Coach settings saved: local model {state}, "
                             f"{settings.get('ai_model')} at {settings.get('ai_url')}")
        return dialog

    def _coach_ready(self, needs_db: bool = True) -> Optional[str]:
        """Return the database path, or ``None`` after saying why the coach waits."""
        path = settings.get("db")
        if needs_db and not path:
            self.logged.emit("The coach reads the habit database. Choose it in "
                             "the Plan or Track form first.")
            return None
        refused = self.coach_guard.allows()
        if refused:
            self.logged.emit(f"The coach stayed quiet, because {refused}")
            return None
        return path or ""

    def _ask_coach(self, path: str, task, show) -> None:
        """Run ``task(con)`` off the window's thread, then ``show(answer)``."""
        def work():
            con = coach_runner.connect(path)
            try:
                return task(con)
            finally:
                con.close()

        def failed(exc):
            self.logged.emit(f"The coach could not answer: {exc}")

        self.coach_runner.run(work, show, failed)

    def _settle(self, path: str, answer, accepted: bool) -> None:
        con = coach_runner.connect(path)
        try:
            coachmod.mark_accepted(con, answer.log_id, accepted)
        finally:
            con.close()

    def rank_grasscatcher(self):
        """Ask the coach to order the grasscatcher, and reorder it on Accept."""
        if self.table is None:
            return None
        entries = self.table.lists.entries(GRASSCATCHER)
        if len(entries) < 2:
            self.logged.emit("The grasscatcher needs two tasks to rank")
            return None
        path = self._coach_ready()
        if path is None:
            return None
        tasks = [(e.code, e.description) for e in entries]
        deadlines = {e.code: (self.table.project_info(e.code) or {}).get("due")
                     for e in entries if e.code}
        planned = self.table.totals()["project"]
        monday = self.week_monday()
        week = monday.isoformat() if monday else None
        model = coach_runner.client()
        result = {}

        def show(answer):
            dialog = coach_runner.SuggestionDialog(
                "Ranked grasscatcher", answer,
                accept_text="Use this order", parent=self)
            accepted = self.run_coach_dialog(dialog)
            if accepted:
                order = [item["index"] for item in answer.data]
                if self.table.lists.reorder(GRASSCATCHER, order):
                    self.table.dirty = True
                    self._reload_list(GRASSCATCHER)
                    self.on_edit()
                self.logged.emit("Put the grasscatcher in the coach's order")
            self._settle(path, answer, accepted)
            result["answer"] = answer

        self._ask_coach(path, lambda con: coachmod.rank_grasscatcher(
            model, tasks, deadlines, planned, con=con, week_start=week), show)
        return result.get("answer")

    def read_weeks(self):
        """Show the two strongest patterns in the record and one change to try."""
        path = self._coach_ready()
        if path is None:
            return None
        monday = self.week_monday()
        end = monday.isoformat() if monday else None
        model = coach_runner.client()
        result = {}

        def show(answer):
            rows = answer.data.get("rows") or []
            numbers = "\n".join(
                f"{r['kind']} {r['group']}: {round(r['adherence'] * 100)}% kept over "
                f"{r['weeks']} weeks" for r in rows)
            if rows:
                numbers += f"\nall weeks: {round(answer.data['overall'] * 100)}% kept"
            dialog = coach_runner.SuggestionDialog(
                "Patterns in your weeks", answer,
                intro=("The numbers behind the reading:\n" + numbers) if rows else "",
                accept_text="Keep the suggestion", parent=self)
            accepted = self.run_coach_dialog(dialog)
            if answer.log_id is not None:
                self._settle(path, answer, accepted)
            result["answer"] = answer

        self._ask_coach(path, lambda con: coachmod.read_weeks(model, con, end), show)
        return result.get("answer")

    # -- quick capture to the grasscatcher (Rule 4) -----------------------------
    def focus_capture(self) -> None:
        """Show the grasscatcher and put the cursor in its capture box."""
        panel = self.list_panels[GRASSCATCHER]
        self.project_tabs.setCurrentWidget(panel)
        panel.capture_edit.setFocus(Qt.ShortcutFocusReason)
        panel.capture_edit.selectAll()

    def capture_projects(self):
        from .. import capture
        legend = {code: description
                  for code, (description, _risk) in self.table.legend().items()}
        lists = [(entry.code, entry.description)
                 for name, _title in LISTS if name not in (GRASSCATCHER, COMPLETED)
                 for entry in self.table.lists.entries(name)]
        return capture.projects_from(legend, lists)

    def capture_task(self, text: str):
        """File a thought typed or dictated in plain words on the grasscatcher.

        The task is added at once, with no dialog, because a capture that
        interrupts is a capture that is skipped. The model is asked only when
        the coach may speak. During a block, or in an AI-off week, the plain
        reading is used without asking, so capturing never breaks deep work.
        """
        if self.table is None or not text.strip():
            return None
        projects = self.capture_projects()
        quiet = None
        try:
            coachmod.check_allowed(self.today(), off_week=settings.get("ai_off_week"))
            monday = self.week_monday()
            if coachmod.block_now(self.table.blocks(), monday,
                                  self.coach_guard.now()) is not None:
                quiet = "you are inside a planned block"
        except coachmod.CoachError as exc:
            quiet = str(exc)
        model = None if quiet else coach_runner.client()
        path = settings.get("db") if model is not None else ""
        monday = self.week_monday()
        week = monday.isoformat() if monday else None
        result = {}

        def work():
            if path:
                con = coach_runner.connect(path)
                try:
                    return coachmod.capture_task(model, text, projects, con=con,
                                                 week_start=week)
                finally:
                    con.close()
            return coachmod.capture_task(model, text, projects)

        def done(answer):
            result["answer"] = answer
            self.add_captured(answer.data)

        self.coach_runner.run(work, done, lambda exc: self.logged.emit(
            f"Could not capture the task: {exc}"))
        return result.get("answer")

    def add_captured(self, captured) -> int:
        """Append a captured task to the grasscatcher.  Return its position."""
        from ..project_lists import Entry
        position = self.table.lists.insert(
            GRASSCATCHER, None, Entry(captured.code, captured.entry_text()))
        self.table.dirty = True
        self._reload_list(GRASSCATCHER)
        panel = self.list_panels[GRASSCATCHER]
        panel.view.setCurrentIndex(panel.model.index(position, 1))
        if panel.capture_edit is not None:
            panel.capture_edit.clear()
        head = f"{captured.code}: " if captured.code else "- "
        self.logged.emit(f"Captured {head}{captured.entry_text()}"
                         + (f" (project from {captured.how})" if captured.code
                            else f" (no project, because {captured.how})"
                            if captured.how else ""))
        self.on_edit()
        return position

    # -- missed-block rescue (Rule 9) ---------------------------------------------
    def rescue_plan(self):
        """Return the rescue decisions for the open week, or ``None`` with a reason logged."""
        from .. import rescue
        monday = self.week_monday()
        path = settings.get("db")
        if self.table is None or monday is None:
            self.logged.emit("The table has no week date, so no block can be "
                             "found missed")
            return None
        if not path:
            self.logged.emit("Missed blocks are found from the sessions in the habit "
                             "database. Choose it in the Plan or Track form first.")
            return None
        con = coach_runner.connect(path)
        try:
            outcomes = reviewmod.block_outcomes(con, monday.isoformat(),
                                                self.today().isoformat())
        finally:
            con.close()
        now = self.coach_guard.now()
        slots = self.energy_slots()
        missed = rescue.missed_blocks(slots, outcomes, monday, now)
        days = sorted({offset for _i, offset, _label in self.table.columns})
        legend = {code: description
                  for code, (description, _risk) in self.table.legend().items()}
        return rescue.plan(slots, missed, self.energy_panel.profile, days, monday,
                           now, legend)

    def rescue_missed(self):
        """Offer to make up the week's missed blocks that are worth rescuing (Rule 9)."""
        found = self.rescue_plan()
        if found is None:
            return None
        profile = self.energy_panel.profile
        week = self.week_monday().isoformat()
        out = {}

        def show(answer, path):
            out["answer"] = answer
            if not found:
                self.logged.emit(answer.data["note"])
                return
            rescues = [r for r in found if r.rescued]
            dialog = coach_runner.SuggestionDialog(
                "Missed blocks", answer, [r.line() for r in rescues],
                intro=answer.data["note"],
                accept_text="Add the checked blocks" if rescues else "Close",
                parent=self)
            accepted = self.run_coach_dialog(dialog)
            if accepted and rescues:
                self.apply_rescues([rescues[i] for i in dialog.chosen()])
            if path and answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._plan_check(lambda model, con: coachmod.rescue_missed(
            model, found, profile, con=con, week_start=week), show)
        return out.get("answer")

    def apply_rescues(self, chosen) -> int:
        """Place a make-up block for each chosen rescue.  Return how many."""
        from .weekly_table import CATEGORY_LETTER
        done, inserted = 0, False
        for r in chosen:
            value = CATEGORY_LETTER.get(r.missed.category, "") + r.missed.code
            try:
                _row, added = self.table.place_block(r.offset, r.start, r.end, value)
            except ValueError as exc:
                self.logged.emit(f"Could not add {r.line()}: {exc}")
                continue
            inserted = inserted or added
            self.logged.emit(r.line())
            done += 1
        if inserted:
            self._rebuild_views()
        if done:
            self.on_grid_edit()
        return done

    # -- project numbering help -------------------------------------------------
    def ask_text(self, title: str, label: str) -> Optional[str]:
        """Ask for one line of text.  A test replaces it."""
        text, ok = QtWidgets.QInputDialog.getText(self, title, label)
        return text.strip() if ok and text.strip() else None

    def numbering_inputs(self):
        """Return ``(known numbers, active numbers, tasks by code, names by code)``."""
        from .. import numbering
        from ..project_lists import project_number
        legend = {code: split_due_date(description)[0]
                  for code, (description, _risk) in self.table.legend().items()}
        listed = [entry.project for name, _title in LISTS if name != GRASSCATCHER
                  for entry in self.table.lists.entries(name)]
        known = numbering.folder_projects(self.projects_root())
        known.update({k: v for k, v in numbering.known_projects(
            legend.values(), listed).items() if k not in known})
        active = [n for n in (project_number(p) for p in list(legend.values()) + [
            e.project for e in self.table.lists.entries(CURRENT_LIST)]) if n]
        tasks: Dict[str, List[str]] = {}
        for entry in self.table.lists.entries(GRASSCATCHER):
            if entry.code:
                tasks.setdefault(entry.code, []).append(entry.description)
        path = settings.get("db")
        if path:
            since = (self.today() - _dt.timedelta(days=56)).isoformat()
            con = coach_runner.connect(path)
            try:
                for code, text in con.execute(
                        "SELECT code, text FROM block_objective WHERE day >= ?", (since,)):
                    if code in legend:
                        tasks.setdefault(code, []).append(text)
            finally:
                con.close()
        return known, active, tasks, legend

    def number_project(self, name: Optional[str] = None):
        """Suggest a number for a new project and offer to add it to the current list."""
        from .. import numbering
        from ..project_lists import Entry
        if self.table is None:
            return None
        name = name or self.ask_text("Number a new project",
                                     "Working name of the new project, such as "
                                     "RET kinase PROTAC degraders:")
        if not name:
            return None
        known, active, tasks, legend = self.numbering_inputs()
        suggestion = numbering.suggest(name, known, active=active)
        found = numbering.forming(tasks, legend)
        monday = self.week_monday()
        week = monday.isoformat() if monday else None
        out = {}

        def show(answer, path):
            out["answer"] = answer
            dialog = coach_runner.SuggestionDialog(
                "Number for a new project", answer,
                [suggestion.line(number) for number in suggestion.numbers],
                intro=answer.data["note"], checked=False,
                accept_text="Add the first checked to the current list", parent=self)
            accepted = self.run_coach_dialog(dialog)
            chosen = dialog.chosen()
            if accepted and chosen:
                number = suggestion.numbers[chosen[0]]
                project = f"{number}{numbering.camel(name)}"
                self.table.lists.insert(CURRENT_LIST, None, Entry(None, project))
                self.table.dirty = True
                self._reload_list(CURRENT_LIST)
                self.logged.emit(f"Added {project} to the current semester list")
                self.on_edit()
            if path and answer.log_id is not None:
                self._settle(path, answer, bool(accepted and chosen))

        self._plan_check(lambda model, con: coachmod.number_project(
            model, suggestion, found, con=con, week_start=week), show)
        return out.get("answer")

    # -- roll-forward triage (Rule 3) ------------------------------------------
    def triage_plan(self):
        """Return ``(decisions, period name)`` for the Carried over list, or ``None``."""
        from .. import triage
        if self.table is None:
            return None
        carried = self.table.lists.entries(CARRIED)
        path = settings.get("db")
        if carried and not path:
            self.logged.emit("Triage reads the minutes logged for each project in "
                             "the habit database. Choose it in the Plan or Track "
                             "form first.")
            return None
        today = self.today()
        period = self.current_period()
        end = period.end if period is not None else today + _dt.timedelta(weeks=16)
        name = period.name if period is not None else "this period"
        titles, _tips = self.list_titles()
        history = {}
        if carried:
            names = {e.code: e.project for e in carried if e.code}
            for code, (description, _risk) in self.table.legend().items():
                names.setdefault(code, split_due_date(description)[0])
            start = (period.start if period is not None else today) - _dt.timedelta(
                weeks=26)
            con = coach_runner.connect(path)
            try:
                history = triage.minutes_by_project(con, names, start.isoformat())
            finally:
                con.close()
        found = triage.triage(carried, history, today, end, titles[HORIZONS[1]])
        return found, name

    def triage_carried(self):
        """Suggest keep, defer, or drop for each carried project, and apply the checked."""
        plan = self.triage_plan()
        if plan is None:
            return None
        found, period = plan
        monday = self.week_monday()
        week = monday.isoformat() if monday else None
        out = {}

        def show(answer, path):
            out["answer"] = answer
            if not found:
                self.logged.emit(answer.data["note"])
                return
            dialog = coach_runner.SuggestionDialog(
                "Carried-over projects", answer, [d.line() for d in found],
                intro=answer.data["note"], accept_text="Apply the checked",
                parent=self)
            accepted = self.run_coach_dialog(dialog)
            if accepted:
                self.apply_triage([found[i] for i in dialog.chosen()])
            if path and answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._plan_check(lambda model, con: coachmod.triage_projects(
            model, found, period, con=con, week_start=week), show)
        return out.get("answer")

    def apply_triage(self, chosen) -> int:
        """Keep, defer, or drop each chosen carried project.  Return how many."""
        from .. import triage
        lists, done = self.table.lists, 0
        for d in chosen:
            position = lists.find_project(CARRIED, d.project)
            if position is None:
                continue
            if d.action == triage.DROP:
                lists.remove(CARRIED, position)
            else:
                lists.transfer(CARRIED, position,
                               CURRENT_LIST if d.action == triage.KEEP else HORIZONS[1])
            self.logged.emit(d.line())
            done += 1
        if done:
            self.table.dirty = True
            for name in (CARRIED, CURRENT_LIST, HORIZONS[1]):
                self._reload_list(name)
            self.on_edit()
        return done

    # -- next week from the progress table (Rule 3) -----------------------------
    #: Minutes shared out when the open week plans no project time to go by.
    DEFAULT_CAPACITY = 600

    def progress_capacity(self) -> int:
        """Return the minutes to share next week: the open week's planned project time."""
        planned = sum(self.table.totals()["project"].values()) if self.table else 0
        return planned or self.DEFAULT_CAPACITY

    def progress_plan(self):
        """Return next week's suggested :class:`~writing_habit.progress.Plan`, or ``None``."""
        from .. import progress
        if self.table is None:
            return None
        rows = progress.read(self.table.lists.lines)
        if rows is None:
            self.logged.emit("The week file has no progress table. Make one on the "
                             "Progress tab first.")
            return None
        return progress.plan(rows, self.progress_capacity(), self.energy_panel.profile)

    def plan_from_progress(self):
        """Suggest next week's plan from the weights and energy, and offer to list it."""
        plan = self.progress_plan()
        if plan is None:
            return None
        monday = self.week_monday()
        week = monday.isoformat() if monday else None
        out = {}

        def show(answer, path):
            out["answer"] = answer
            if not plan.shares:
                self.logged.emit(answer.data["note"])
                return
            from .. import progress
            profile = self.energy_panel.profile
            dialog = coach_runner.ProgressPlanDialog(
                answer, plan, lambda rows: progress.plan(rows, plan.capacity, profile),
                parent=self)
            out["dialog"] = dialog
            accepted = self.run_coach_dialog(dialog)
            if accepted:
                checked = dialog.checked_rows()
                planned = [row for row, _m in dialog.plan.shares]
                if [r.number for r in checked] != [r.number for r in planned]:
                    dialog.update_plan()        # boxes changed after the last update
                final = dialog.plan
                chosen = [row for row, _m in final.shares]
                self.add_to_next_week(chosen)
                QtWidgets.QApplication.clipboard().setText(
                    "\n".join(b.line() for b in final.blocks))
                self.logged.emit("Copied next week's suggested blocks to the clipboard")
            if path and answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._plan_check(lambda model, con: coachmod.progress_plan(
            model, plan, con=con, week_start=week), show)
        self.last_progress_dialog = out.get("dialog")
        return out.get("answer")

    def add_to_next_week(self, rows) -> int:
        """Put each progress row's project on the Next week list.  Return how many."""
        from ..project_lists import Entry
        lists, added = self.table.lists, 0
        target = WEEKS[0]
        have = {e.project[:4] for e in lists.entries(target)}
        current = {e.project[:4]: e for e in lists.entries(CURRENT_LIST)}
        for row in rows:
            if row.number in have:
                continue
            entry = current.get(row.number)
            entry = (Entry(None, entry.description, entry.risk, entry.activity)
                     if entry else Entry(None, f"{row.number}{row.name}"))
            lists.insert(target, None, entry)
            have.add(row.number)
            added += 1
        if added:
            self.table.dirty = True
            self._reload_list(target)
            self.on_edit()
            self.logged.emit(f"Added {added} project{'' if added == 1 else 's'} "
                             "to the Next week list")
        return added

    # -- stuck projects (Rule 4) -----------------------------------------------
    def find_stuck(self):
        """Report the week's projects that keep missing their objectives."""
        from .. import stuck
        if self.table is None:
            return None
        path = settings.get("db")
        if not path:
            self.logged.emit("The objectives live in the habit database. Choose it "
                             "in the Plan or Track form first.")
            return None
        con = coach_runner.connect(path)
        try:
            found = stuck.find(con, list(self.table.legend()),
                               today=self.today().isoformat())
        finally:
            con.close()
        text = stuck.report(found)
        if not found:
            self.logged.emit(text)
            return found
        answer = coachmod.Answer(data=found, text=text, facts="",
                                 source="plain summary written without a model")
        dialog = coach_runner.SuggestionDialog("Stuck projects", answer,
                                               accept_text="Close", parent=self)
        self.run_coach_dialog(dialog)
        return found

    # -- planning checks: deadlines and energy (Rules 2 and 3) -------------------
    def _plan_check(self, work, show) -> None:
        """Run ``work(model, con)`` and pass its answer to ``show``.

        The checks are made by the software, so they run without a habit
        database and while the coach must stay quiet. The model only words the
        note, and it is asked only when Rule 10 allows. A check made without the
        model in an AI-off week or a block is not logged, so the week still
        counts as a week without the coach.
        """
        path = settings.get("db")
        refused = self.coach_guard.allows()
        model = None if refused else coach_runner.client()
        log = bool(path) and not refused

        def finish(answer):
            if refused:
                answer.source = ("plain summary written without a model, because "
                                 f"{refused}")
            show(answer, path if log else None)

        if log:
            self._ask_coach(path, lambda con: work(model, con), finish)
        else:
            self.coach_runner.run(lambda: work(model, None), finish,
                                  lambda exc: self.logged.emit(
                                      f"The check could not run: {exc}"))

    def coverage_result(self):
        """Return the deadline coverage of the open week, or ``None``."""
        monday = self.week_monday()
        if self.table is None or monday is None:
            return None
        legend = {code: description
                  for code, (description, _risk) in self.table.legend().items()}
        lists = [(name, entry.code, entry.description)
                 for name, _title in LISTS if name not in (GRASSCATCHER, COMPLETED)
                 for entry in self.table.lists.entries(name)]
        slots = [deadlinesmod.Slot(b.offset, b.start, b.end, b.letter, b.category,
                                   b.minutes, b.row, b.column)
                 for b in self.table.blocks()]
        try:
            horizon = int(settings.get("coverage_days") or deadlinesmod.HORIZON_DAYS)
        except ValueError:
            horizon = deadlinesmod.HORIZON_DAYS
        return deadlinesmod.check(legend, lists, slots, monday, self.today(), horizon)

    def check_coverage(self):
        """Find projects due soon with no block left this week (Rule 3)."""
        if self.table is None:
            return None
        result = self.coverage_result()
        if result is None:
            self.logged.emit("The table has no week date, so its deadlines "
                             "cannot be checked")
            return None
        week = self.week_monday().isoformat()
        out = {}

        def show(answer, path):
            out["answer"] = answer
            risks = [r for r in result.risks if r.donor is not None]
            if not result.risks:
                self.logged.emit(answer.data["note"])
                return
            dialog = coach_runner.SuggestionDialog(
                "Deadlines and this week's plan", answer,
                [deadlinesmod.proposal_line(r) for r in risks],
                intro=answer.data["note"], accept_text="Make the checked changes",
                parent=self)
            accepted = self.run_coach_dialog(dialog)
            if accepted and risks:
                self.apply_coverage([risks[i] for i in dialog.chosen()])
            if path and answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._plan_check(lambda model, con: coachmod.cover_deadlines(
            model, result, con=con, week_start=week), show)
        return out.get("answer")

    def apply_coverage(self, risks) -> int:
        """Give each risk's proposed block to its project.  Return how many changed."""
        changed = 0
        for risk in risks:
            block = self.table.block_at(risk.donor.row, risk.donor.column)
            if block is None or block.letter != risk.donor.code:
                continue
            code = risk.project.code if risk.project.in_legend else None
            if code is None:
                entry = next((e for e in self.table.lists.entries(risk.project.source)
                              if e.project == risk.project.name), None)
                if entry is None:
                    continue
                row = self.table.copy_to_legend(entry)
                code = self.table.rows[row].parsed[0]
                self._rebuild_views()
                block = self.table.block_at(risk.donor.row, risk.donor.column)
            self.table.give_block(block, code)
            self.logged.emit(f"Gave {risk.donor.label()} to {code} "
                             f"{risk.project.name}, due {risk.project.deadline}")
            changed += 1
        if changed:
            self.on_edit()
        return changed

    # -- energy ------------------------------------------------------------------
    def energy_slots(self):
        return [energymod.Slot(b.offset, b.start, b.end, b.letter, b.category,
                               b.minutes, b.row, b.column)
                for b in self.table.blocks()] if self.table is not None else []

    def _movable(self):
        """Return a test for blocks still ahead, so a swap never rewrites the past."""
        monday = self.week_monday()
        if monday is None:
            return lambda slot: True
        today = self.today()
        return lambda slot: monday + _dt.timedelta(days=slot.offset) >= today

    def _refresh_energy(self) -> None:
        if not hasattr(self, "energy_panel"):
            return
        profile = self.energy_panel.profile
        found = energymod.misfits(profile, self.energy_slots())
        proposed = energymod.swaps(profile, self.energy_slots(), self._movable())
        self.energy_panel.show_report(energymod.plain(profile, found, proposed))
        index = self.panels.indexOf(self.energy_panel)
        self.panels.setTabText(index, f"Energy ({len(found)})" if found else "Energy")

    def on_energy_changed(self) -> None:
        settings.put("energy_profile", energymod.dump(self.energy_panel.profile))
        self._refresh_energy()

    def energy_from_reviews(self):
        """Offer a profile drawn from the focus ratings of reviewed blocks."""
        path = settings.get("db")
        if not path:
            self.logged.emit("The focus ratings live in the habit database. "
                             "Choose it in the Plan or Track form first.")
            return None
        con = coach_runner.connect(path)
        try:
            new, changes = energymod.from_reviews(con, self.energy_panel.profile)
        finally:
            con.close()
        if not changes:
            self.logged.emit(
                "No hour has enough focus ratings to change your energy profile "
                f"yet. An hour needs {energymod.MIN_REVIEWS} rated blocks of one "
                "activity.")
            return []
        lines = [f"{c.activity.capitalize()} at {c.hour:02d}:00 from "
                 f"{energymod.LEVELS[c.old]} to {energymod.LEVELS[c.new]}, "
                 f"mean focus {c.mean} over {c.reviews} blocks" for c in changes]
        answer = coachmod.Answer(data=None, text="", facts="",
                                 source="plain summary written without a model")
        dialog = coach_runner.SuggestionDialog(
            "Energy from your focus ratings", answer, lines,
            intro="Your focus ratings suggest these changes. Check the ones to keep.",
            accept_text="Change the checked hours", parent=self)
        if self.run_coach_dialog(dialog):
            profile = {a: list(levels) for a, levels in self.energy_panel.profile.items()}
            for i in dialog.chosen():
                profile[changes[i].activity][changes[i].hour] = changes[i].new
            self.energy_panel.set_profile(profile)
            self.logged.emit(f"Changed {len(dialog.chosen())} hour(s) of your "
                             "energy profile from your focus ratings")
        return changes

    def match_energy(self):
        """Find blocks that do not fit the energy profile, and propose swaps (Rule 2)."""
        if self.table is None:
            return None
        profile = self.energy_panel.profile
        slots = self.energy_slots()
        found = energymod.misfits(profile, slots)
        proposed = energymod.swaps(profile, slots, self._movable())
        monday = self.week_monday()
        week = monday.isoformat() if monday else None
        out = {}

        def show(answer, path):
            out["answer"] = answer
            if not found:
                self.logged.emit(answer.data["note"])
                return
            dialog = coach_runner.SuggestionDialog(
                "Blocks and your energy", answer,
                [energymod.swap_line(w) for w in proposed],
                intro=answer.data["note"],
                accept_text="Swap the checked blocks" if proposed else "Close",
                parent=self)
            accepted = self.run_coach_dialog(dialog)
            if accepted and proposed:
                self.apply_swaps([proposed[i] for i in dialog.chosen()])
            if path and answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._plan_check(lambda model, con: coachmod.match_energy(
            model, profile, found, proposed, con=con, week_start=week), show)
        return out.get("answer")

    def apply_swaps(self, chosen) -> int:
        """Exchange the work of each chosen pair of blocks.  Return how many."""
        moves, done = [], 0
        for w in chosen:
            a = self.table.block_at(w.first.row, w.first.column)
            b = self.table.block_at(w.second.row, w.second.column)
            if a is None or b is None or (a.letter, b.letter) != (w.first.code, w.second.code):
                continue
            self.table.swap_blocks(a, b)
            # Objectives follow their project. Two blocks of one project swap
            # only their activities, so their objectives stay where they are.
            if a.letter != b.letter:
                moves += [(a, b.start, b.end), (b, a.start, a.end)]
            self.logged.emit(energymod.swap_line(w))
            done += 1
        if done:
            self._rekey(moves)
            self.on_edit()
        return done

    def partner_summary(self):
        """Draft the open week's summary for an accountability partner (Rule 8).

        The summary needs no model, so it is offered even when the coach must
        stay quiet. In an AI-off week, or when the writer declines to ask the
        coach during a block, the plain summary is shown and nothing is written
        to the ``ai_log`` table, so the week still counts as a week without AI.
        """
        path = settings.get("db")
        if not path:
            self.logged.emit("The partner summary reads the habit database. "
                             "Choose it in the Plan or Track form first.")
            return None
        monday = self.week_monday()
        if monday is None:
            self.logged.emit("The table has no week date, so there is no week "
                             "to summarize")
            return None
        week = monday.isoformat()
        today = self.today().isoformat()
        refused = self.coach_guard.allows()
        model = None if refused else coach_runner.client()
        log = not refused
        result = {}

        def show(answer):
            result["answer"] = answer
            if answer.data is None:
                self.logged.emit(answer.text)
                return
            if refused:
                answer.source = ("plain summary written without a model, because "
                                 f"{refused}")
            dialog = coach_runner.PartnerDialog(answer, parent=self)
            accepted = self.run_coach_dialog(dialog)
            if accepted:
                QtWidgets.QApplication.clipboard().setText(dialog.text())
                self.logged.emit("Copied the summary for your partner to the "
                                 "clipboard")
            if answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._ask_coach(path, lambda con: coachmod.partner_summary(
            model, con, week, today=today, log=log), show)
        return result.get("answer")

    def ask_misses(self):
        """Ask one question about each missed block of the open week (Rule 6)."""
        from .. import misses
        path = settings.get("db")
        if not path:
            self.logged.emit("Missed blocks are found from the sessions in the habit "
                             "database. Choose it in the Plan or Track form first.")
            return None
        monday = self.week_monday()
        if monday is None:
            self.logged.emit("The table has no week date, so no block can be "
                             "found missed")
            return None
        week = monday.isoformat()
        con = coach_runner.connect(path)
        try:
            found = misses.find(con, week, self.today().isoformat())
        finally:
            con.close()
        if not found:
            self.logged.emit(misses.intro(found))
            return found
        refused = self.coach_guard.allows()
        model = None if refused else coach_runner.client()
        result = {}

        def show(answer):
            result["answer"] = answer
            if refused:
                answer.source = ("plain summary written without a model, because "
                                 f"{refused}")
            answer.data["intro"] = misses.intro(found)
            dialog = coach_runner.MissesDialog(answer, parent=self)
            accepted = self.run_coach_dialog(dialog)
            if accepted:
                con = coach_runner.connect(path)
                try:
                    for miss, question, reason in zip(found, answer.data["questions"],
                                                      dialog.answers()):
                        misses.save(con, miss, question, reason)
                finally:
                    con.close()
                saved = sum(bool(r) for r in dialog.answers())
                self.logged.emit(f"Saved {saved} reason{'' if saved == 1 else 's'} "
                                 "for missed blocks")
            if answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._ask_coach(path, lambda con: coachmod.ask_misses(
            model, found, con=None if refused else con, week_start=week), show)
        return result.get("answer")

    def plan_message(self):
        """Draft the Monday message that tells a partner the week's plan (Rule 8)."""
        from .. import weekplan
        if self.table is None:
            return None
        monday = self.week_monday()
        if monday is None:
            self.logged.emit("The table has no week date, so there is no week to "
                             "describe")
            return None
        week = monday.isoformat()
        blocks = self.table.blocks()
        legend = {code: description
                  for code, (description, _risk) in self.table.legend().items()}
        path = settings.get("db")
        objectives = []
        if path:
            con = coach_runner.connect(path)
            try:
                reviewmod.ensure(con)
                objectives = [(r[0], r[1]) for r in con.execute(
                    "SELECT code, text FROM block_objective WHERE week_start = ?"
                    " AND done = 0 ORDER BY day, start_time, position, objective_id",
                    (week,))]
            finally:
                con.close()
        plan = weekplan.gather(week, self.table.totals()["project"], legend,
                               len(blocks), len({b.offset for b in blocks}), objectives)
        if plan is None:
            self.logged.emit("The week has no blocks yet, so there is no plan to tell")
            return None
        refused = self.coach_guard.allows()
        model = None if refused else coach_runner.client()
        result = {}

        def show(answer):
            result["answer"] = answer
            if refused:
                answer.source = ("plain summary written without a model, because "
                                 f"{refused}")
            dialog = coach_runner.PartnerDialog(
                answer, parent=self, title="Monday message for your writing partner",
                intro=("The week's plan for your accountability partner. Edit it as "
                       "you like, then copy it into a message. Nothing is sent "
                       "for you."))
            accepted = self.run_coach_dialog(dialog)
            if accepted:
                QtWidgets.QApplication.clipboard().setText(dialog.text())
                self.logged.emit("Copied the Monday message to the clipboard")
            if answer.log_id is not None:
                self._settle(path, answer, accepted)

        if path:
            self._ask_coach(path, lambda con: coachmod.plan_message(
                model, plan, con=None if refused else con, week_start=week), show)
        else:
            self.coach_runner.run(lambda: coachmod.plan_message(model, plan), show,
                                  lambda exc: self.logged.emit(
                                      f"The coach could not answer: {exc}"))
        return result.get("answer")

    def semester_span(self):
        """Return ``(name, start, end)`` of the semester the lists are filed under.

        The calendar names it. Without a calendar, the last sixteen weeks up to
        today stand in for it.
        """
        today = self.today()
        period = None
        filed = self.table.lists.period() if self.table is not None else None
        if self.calendar is not None and filed:
            period = self.calendar.find(self.period_kind(), filed)
        period = period or self.current_period()
        if period is not None:
            return period.name, period.start, min(period.end, today)
        return "this semester", today - _dt.timedelta(weeks=16), today

    def semester_review(self):
        """Draft a narrative of the semester for an annual faculty report."""
        from .. import semester as semestermod
        path = settings.get("db")
        if not path:
            self.logged.emit("The semester review reads the habit database. "
                             "Choose it in the Plan or Track form first.")
            return None
        name, start, end = self.semester_span()
        completed = ([e.description for e in self.table.lists.entries(COMPLETED)]
                     if self.table is not None else [])
        con = coach_runner.connect(path)
        try:
            found = semestermod.gather(con, name, start.isoformat(), end.isoformat(),
                                       completed)
        finally:
            con.close()
        if found is None:
            self.logged.emit(f"No week from {start} to {end} has a plan in the habit "
                             "database, so there is no semester to review.")
            return None
        refused = self.coach_guard.allows()
        model = None if refused else coach_runner.client()
        monday = self.week_monday()
        week = monday.isoformat() if monday else None
        result = {}

        def show(answer):
            result["answer"] = answer
            if refused:
                answer.source = ("plain summary written without a model, because "
                                 f"{refused}")
            dialog = coach_runner.PartnerDialog(
                answer, parent=self, title=f"Semester review of {name}",
                intro=("A short account of the semester's writing for your annual "
                       "report, in your voice. Edit it, then copy it into the "
                       "report. Every number comes from the habit database."))
            accepted = self.run_coach_dialog(dialog)
            if accepted:
                QtWidgets.QApplication.clipboard().setText(dialog.text())
                self.logged.emit("Copied the semester review to the clipboard")
            if answer.log_id is not None:
                self._settle(path, answer, accepted)

        self._ask_coach(path, lambda con: coachmod.semester_review(
            model, found, con=None if refused else con, week_start=week), show)
        return result.get("answer")

    def size_week(self):
        """Suggest how many minutes to plan for the open week."""
        if self.table is None:
            return None
        path = self._coach_ready()
        if path is None:
            return None
        monday = self.week_monday()
        if monday is None:
            self.logged.emit("The table has no week date, so there is no week to size")
            return None
        week = monday.isoformat()
        code, _problem = self.table.code_or_problem()
        current = sum(self.table.totals()["project"].values())
        model = coach_runner.client()
        result = {}

        def task(con):
            tags = [r[0] for r in con.execute(
                "SELECT tag FROM week_context WHERE week_start = ?", (week,))]
            size = coachmod.size_next_week(con, week, schedule_code=code, tags=tags)
            if size is None:
                return None
            size["current"] = current
            return coachmod.explain_size(model, size, con=con, week_start=week)

        def show(answer):
            if answer is None:
                self.logged.emit("There are no earlier planned weeks to size this "
                                 "week from yet")
                return
            dialog = coach_runner.SuggestionDialog(
                "A plan size for this week", answer, accept_text="Keep this size",
                parent=self)
            accepted = self.run_coach_dialog(dialog)
            self._settle(path, answer, accepted)
            result["answer"] = answer

        self._ask_coach(path, task, show)
        return result.get("answer")

    def commit_grasscatcher(self, position: int, block=None) -> Optional[int]:
        """Make grasscatcher task ``position`` an objective of the selected block."""
        block = block or self.selected_block()
        if block is None:
            self.logged.emit("Select a block in the grid, then commit a task to it")
            return None
        from .review_panel import ReviewPanel
        panel = ReviewPanel(self.table, self.week_monday(), [block])
        panel.logged.connect(self.logged)
        if not panel.ready():
            self.logged.emit(panel.problem.text())
            return None
        objective_id = panel.commit_from_grasscatcher(position)
        if objective_id is not None:
            self._on_review_table_edit()
        return objective_id

    def shift_selected(self, minutes: int, push: Optional[bool] = None):
        """Move the selected block ``minutes`` later, or earlier when negative.

        The selection follows the block, so pressing the button again keeps
        moving it. Return the moves made, or ``None`` when nothing moved.
        """
        block = self.selected_block()
        if block is None:
            self.logged.emit("Select a block before shifting it")
            return None
        if push is None:
            push = self.push_box.isChecked()
        try:
            (row, column), moves = self.table.shift_block(
                block.row, block.column, minutes, push=push)
        except ValueError as exc:
            self.logged.emit(f"Cannot shift the block: {exc}")
            return None
        self._rekey(moves)
        self._rebuild_views()
        self.on_grid_edit()
        start = self.table.rows[row].parsed[0]
        if self.hour_view_shown():
            hour = int(start[:2])
            grid_column = 1 + [c for c, _o, _l in self.table.columns].index(column)
            self.hour_view.setCurrentIndex(self.hour_model.index(hour, grid_column))
        else:
            grid_row = self.model._rows.index(row)
            grid_column = [c for c, _o, _l in self.table.columns].index(column) + 1
            self.view.setCurrentIndex(self.model.index(grid_row, grid_column))
        first, rest = moves[0], moves[1:]
        text = (f"Shifted {first[0].letter} from {first[0].start}-{first[0].end} "
                f"to {first[1]}-{first[2]}")
        if rest:
            text += "; pushed down " + ", ".join(
                f"{b.letter} to {s}-{e}" for b, s, e in rest)
        self.logged.emit(text)
        self._update_shift_buttons()
        return moves

    def drag_block(self, block, start: str, end: str, offset: int,
                   push: Optional[bool] = None):
        """Carry out a drag in the hour view: a new range, a new day, or both."""
        if offset == block.offset:
            return self.resize_block(block, start, end, push=push)
        if self.table is None:
            return None
        if push is None:
            push = self.push_box.isChecked()
        try:
            (row, column), pushed = self.table.move_block_to(
                block.row, block.column, offset, start, end, push=push)
        except ValueError as exc:
            self.logged.emit(f"Cannot move the block: {exc}")
            return None
        moved = dataclasses.replace(block, offset=offset)
        self._rekey(pushed)
        self._rekey_to(block, moved, start)
        self._rebuild_views()
        self.on_grid_edit()
        grid_column = 1 + [c for c, _o, _l in self.table.columns].index(column)
        if self.hour_view_shown():
            self.hour_view.setCurrentIndex(self.hour_model.index(int(start[:2]), grid_column))
        day = self.table.day_labels[grid_column - 1]
        text = (f"Moved {block.letter} from {self.table.day_labels[[o for _i, o, _l in self.table.columns].index(block.offset)]} "
                f"{block.start}-{block.end} to {day} {start}-{end}")
        if pushed:
            text += "; pushed down " + ", ".join(
                f"{b.letter} to {s}-{e}" for b, s, e in pushed)
        self.logged.emit(text)
        self._update_shift_buttons()
        return [(block, start, end)] + list(pushed)

    def _rekey_to(self, old_block, new_block, start: str) -> None:
        """Carry a block's objectives and review to another day and start."""
        path = settings.get("db")
        if not path or self.week_monday() is None:
            return
        try:
            con = dbmod.connect(path)
            try:
                reviewmod.ensure(con)
                reviewmod.rekey(con, self._block_key(old_block),
                                self._block_key(new_block, start))
            finally:
                con.close()
        except Exception as exc:                         # pragma: no cover
            self.logged.emit(f"Could not move the review with the block: {exc}")

    def resize_block(self, block, start: str, end: str, push: Optional[bool] = None):
        """Give ``block`` the range ``start``-``end``, as dragging an edge asks.

        Later blocks the longer range would overlap move down when **Push
        later blocks down** is checked, and the objectives and review of the
        block follow its new start. Return the moves made, or ``None`` when
        the resize is refused.
        """
        if self.table is None:
            return None
        if push is None:
            push = self.push_box.isChecked()
        try:
            (row, column), moves = self.table.resize_block(
                block.row, block.column, start, end, push=push)
        except ValueError as exc:
            self.logged.emit(f"Cannot resize the block: {exc}")
            return None
        self._rekey(moves)
        self._rebuild_views()
        self.on_grid_edit()
        new_start = self.table.rows[row].parsed[0]
        grid_column = 1 + [c for c, _o, _l in self.table.columns].index(column)
        if self.hour_view_shown():
            self.hour_view.setCurrentIndex(
                self.hour_model.index(int(new_start[:2]), grid_column))
        text = (f"Resized {block.letter} from {block.start}-{block.end} "
                f"to {moves[0][1]}-{moves[0][2]}")
        if moves[1:]:
            text += "; pushed down " + ", ".join(
                f"{b.letter} to {s}-{e}" for b, s, e in moves[1:])
        self.logged.emit(text)
        self._update_shift_buttons()
        return moves

    def drop_unused_rows(self, confirm: bool = True) -> int:
        """Delete the time-block rows with no filled cell, after asking.

        A copy of the file as it is on disk is kept beside it with ``.bak``
        added, and nothing else is written until the writer saves. Return the
        number of rows deleted.
        """
        if self.table is None:
            return 0
        unused = self.table.unused_block_rows()
        if not unused:
            self.logged.emit("Every time-block row holds at least one block")
            return 0
        keep = len(self.table.block_rows) - len(unused)
        if confirm and not self._confirm(
                "Drop unused time rows",
                f"Delete {len(unused)} empty time-block row(s) and keep the "
                f"{keep} that hold blocks?\n\nThe printed sheets do not "
                "change, because they draw every hour whatever rows the table "
                "holds. A .bak copy of the file on disk is kept, and nothing "
                "else is written until you save."):
            return 0
        if self.table.path and Path(self.table.path).is_file():
            backup = Path(self.table.path + ".bak")
            backup.write_bytes(Path(self.table.path).read_bytes())
            self.logged.emit(f"Kept a copy at {backup}")
        dropped = self.table.drop_unused_block_rows()
        self._rebuild_views()
        self.logged.emit(f"Dropped {dropped} unused time row(s)")
        self.on_grid_edit()
        return dropped

    def save(self) -> Optional[str]:
        """Write the table back to the file it came from."""
        if self.table is None:
            return None
        if not self.table.path:
            return self.save_as()
        path = self.table.save()
        self.refresh()
        self.logged.emit(f"Saved {path}")
        self.saved.emit(path)
        return path

    def suggested_name(self) -> str:
        """Return the canonical file name for the grid, or the current name."""
        code, _problem = self.table.code_or_problem() if self.table else (None, None)
        if code:
            return f"{code}.org"
        return Path(self.table.path).name if self.table and self.table.path else "week.org"

    def save_as(self) -> Optional[str]:
        """Write the table to a new file, offering its canonical name."""
        if self.table is None:
            return None
        folder = Path(self.table.path).parent if self.table.path else Path(
            settings.get("table_dir") or Path.home())
        path, _filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save the weekly table", str(folder / self.suggested_name()),
            "Org files (*.org);;All files (*)")
        if not path:
            return None
        written = self.table.save(path)
        self.refresh()
        self.logged.emit(f"Saved {written}")
        self.saved.emit(written)
        return written

    def rename_to_canonical(self) -> Optional[str]:
        """Move the open file to the canonical name of its grid."""
        if self.table is None:
            return None
        try:
            path = self.table.rename_to_canonical()
        except ValueError as exc:
            self.logged.emit(f"Cannot rename: {exc}")
            QtWidgets.QMessageBox.information(self, "Rename", str(exc))
            return None
        self.refresh()
        self.logged.emit(f"Renamed to {path}")
        self.saved.emit(path)
        return path

    def scaffold(self, projects: Optional[int] = None,
                 style: Optional[str] = None) -> None:
        """Start a blank table for N projects, using the scheduler's own scaffold.

        The scheduler's scaffold stops at 26 projects, one per letter. Beyond
        that the legend is extended here with the two-letter codes ``AA``,
        ``AB``, and so on, up to the 702 codes there are. ``style`` is
        ``standard`` or one of the three-block starter days ``morning``,
        ``evening``, and ``split``, and the window asks for it when the
        project count was asked for too.
        """
        from writing_schedule.template import template_string

        if projects is None:
            projects, accepted = QtWidgets.QInputDialog.getInt(
                self, "New weekly table", "Number of projects", 3, 1,
                len(PROJECT_CODES))
            if not accepted:
                return
            if style is None:
                labels = [label for label, _style in TEMPLATE_CHOICES]
                label, accepted = QtWidgets.QInputDialog.getItem(
                    self, "New weekly table", "Shape of the day", labels, 0, False)
                if not accepted:
                    return
                style = dict(TEMPLATE_CHOICES)[label]
        style = style or "standard"
        projects = max(1, min(int(projects), len(PROJECT_CODES)))
        try:
            text = template_string(min(projects, 26), style)
        except TypeError:                   # writing-schedule older than 0.4
            if style != "standard":
                self.logged.emit("Starter days need writing-schedule 0.4 or newer")
                return
            text = template_string(min(projects, 26))
        previous = self.table
        self.table = WeeklyTable(text)
        # A new week keeps the semester lists of the week it replaces.
        if previous is not None and self.table.adopt_lists(previous):
            self.logged.emit("Kept the semester project lists of the previous table")
        for _extra in range(projects - len(self.table.legend())):
            self.table.add_legend(self.table.next_free_code())
        self.model.set_table(self.table)
        self.legend_model.set_table(self.table)
        self.table.dirty = True
        for button in (self.save_button, self.save_as_button,
                       self.project_above_button, self.project_below_button,
                       self.hour_button, self.more_button):
            button.setEnabled(True)
        self.reload_button.setEnabled(False)
        self._update_insert_buttons()
        self._fit_columns()
        self.refresh()
        self.logged.emit(f"Scaffolded a blank table for {projects} project(s)"
                         + ("" if style == "standard" else f", {style} day"))

    # -- readings ----------------------------------------------------------
    def refresh(self) -> None:
        """Recompute the four panels from the current table."""
        if self.table is None:
            return
        name = self.table.path or "(unsaved table)"
        self.path_label.setText(name + ("  *" if self.table.dirty else ""))
        self.path_label.setToolTip(name)
        self.save_button.setEnabled(self.table.dirty)
        self.external_button.setEnabled(bool(self.table.path))
        self.rename_button.setEnabled(
            bool(self.table.path) and not self.table.dirty
            and not self.table.name_matches_code())
        self.model.refresh()
        if self.hour_model.table is not self.table:
            self.hour_model.set_table(self.table)
            self._fit_hour_columns()
        else:
            self.hour_model.refresh()
        self._update_project_move_buttons()
        self.name_panel.setPlainText(self._name_text())
        self.clash_panel.setPlainText(self._clash_text())
        self.totals_panel.setPlainText(self._totals_text())
        self.legend_panel.setPlainText(self._legend_text())
        self.break_panel.setPlainText(self._break_text())
        self.update_period_banner()
        clashes = len(self.table.overlaps())
        self.panels.setTabText(1, "Clashes" if not clashes else f"Clashes ({clashes})")
        runs = len(self.table.break_runs())
        self.panels.setTabText(2, "Breaks" if not runs else f"Breaks ({runs})")
        self._refresh_energy()

    def _name_text(self) -> str:
        code, problem = self.table.code_or_problem()
        if code is None:
            return "This week has no canonical file name.\n\n" + problem
        lines = [f"Canonical file name:  {code}.org", ""]
        if self.table.path:
            stem = Path(self.table.path).stem
            if stem != code:
                lines.append(f"The file is named {stem}.org, which is not the "
                             f"canonical form of this grid.")
                lines.append("")
        from .. import name as namemod
        decoded = namemod.decode(code)
        lines.append(namemod.format_week(decoded))
        total, activities, projects = namemod.summary(decoded)
        lines.append("")
        lines.append(f"{total} blocks over {len(decoded)} days")
        lines.append("by activity: " + ", ".join(
            f"{count} {activity}" for activity, count in sorted(activities.items())))
        lines.append("by project:  " + ", ".join(
            f"{project} ({count})" for project, count in sorted(projects.items())))
        return "\n".join(lines)

    def _clash_text(self) -> str:
        from writing_schedule.overlap import overlap_lines
        conflicts = self.table.overlaps()
        if not conflicts:
            return "No overlapping time blocks."
        head = [f"{len(conflicts)} overlapping pair(s). The cells are tinted.", ""]
        return "\n".join(head + list(overlap_lines(conflicts)))

    def _break_text(self) -> str:
        from .weekly_table import BREAK_GAP, PICK_MAX
        runs = self.table.break_runs()
        if not runs:
            return (f"Every day has a break of at least {BREAK_GAP} minutes "
                    f"within each {PICK_MAX // 60} hours of blocks.")
        labels = {offset: label for _i, offset, label in self.table.columns}
        lines = [f"{len(runs)} run(s) of blocks go more than {PICK_MAX // 60} "
                 f"hours without a {BREAK_GAP}-minute break. The cells are "
                 "tinted amber.", ""]
        for run in runs:
            hours, minutes = divmod(run.minutes, 60)
            codes = ", ".join(f"{b.letter} {b.start}-{b.end}" for b in run.blocks)
            lines.append(f"{labels.get(run.offset, run.offset)}  {run.start}-{run.end}"
                         f"  ({hours}:{minutes:02d})  {codes}")
        return "\n".join(lines)

    def _totals_text(self) -> str:
        totals = self.table.totals()
        lines = ["Planned minutes", ""]
        for title, key in (("By day", "day"), ("By project", "project"),
                           ("By activity", "category")):
            lines.append(title)
            for label, minutes in totals[key].items():
                hours = minutes / 60
                lines.append(f"  {label:<12} {minutes:>5} min  ({hours:.1f} h)")
            lines.append("")
        grand = sum(totals["day"].values())
        lines.append(f"Week total   {grand} min  ({grand / 60:.1f} h)")
        fallbacks = self.table.activity_fallbacks()
        if fallbacks:
            lines += ["", "Blocks with no activity letter, no project default, "
                          "and no section, counted as generative:"]
            days = {offset: label for _i, offset, label in self.table.columns}
            lines += [f"  {days.get(b.offset, b.offset)} {b.start}-{b.end} {b.letter}"
                      for b in fallbacks]
        unknown = self.table.unknown_sections()
        if unknown:
            lines += ["", "Sections with no activity category, counted as "
                          "generative by the plan importer:"]
            lines += [f"  {name}" for name in unknown]
        return "\n".join(lines)

    def _legend_text(self) -> str:
        rows, problems = self.table.legend_check()
        lines = ["Project letters resolved against the legend", ""]
        for letter, code, description, risk, status in rows:
            tag = f" [{risk}]" if risk else ""
            lines.append(f"  {letter:<4} -> {code:<5} {description}{tag}  ({status})")
        if problems:
            lines += ["", "Unresolved: " + ", ".join(problems)]
        else:
            lines += ["", "Every project letter resolves to one legend entry."]
        unused = [code for code in self.table.legend()
                  if code not in {row[1] for row in rows}]
        if unused:
            lines += ["", "Legend entries not used this week: " + ", ".join(unused)]

        duplicates = self.table.duplicate_legend_codes()
        if duplicates:
            lines += ["", "Codes defined more than once. The readers keep the "
                          "first and drop the rest:"]
            for code, descriptions in duplicates.items():
                lines.append(f"  {code}: " + " | ".join(descriptions))

        overrides = self.table.prefix_overrides()
        if overrides:
            lines += ["", "Cells whose activity letter overrides their section:"]
            for b in overrides:
                lines.append(f"  {b.start}-{b.end} {self.table.cell(b.row, b.column)} "
                             f"under {b.section} counts as {b.category}")
        defaults = self.table.legend_defaults()
        if defaults:
            lines += ["", "Default activities: " + ", ".join(
                f"{code} {activity}" for code, activity in defaults.items())]

        stray = self.table.stray_risk_tags()
        if stray:
            lines += ["", "Risk tags that name no class, so these projects stay "
                          "out of the barbell comparison:"]
            for code, tag in stray:
                lines.append(f"  {code}: :{tag}:  (write :safe: or :speculative:)")
        return "\n".join(lines)
