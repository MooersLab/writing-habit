"""The Energy tab: the writer's best hours for each kind of writing.

A grid of the 24 hours by the three activities holds the energy profile of
:mod:`writing_habit.energy`. Clicking a cell steps it through Low, Medium, and
High. **Reset to defaults** restores a common pattern, and **From my focus
ratings** proposes a profile from the focus ratings of reviewed blocks. Below
the grid the tab lists the week's blocks that do not fit the profile, and
**Match blocks to my energy** proposes swaps. The profile is kept with the
other preferences.
"""

from __future__ import annotations

from typing import Dict, List

from .. import energy
from .qt import QtGui, QtWidgets, pyqtSignal

LABELS = {energy.LOW: "Low", energy.MEDIUM: "Medium", energy.HIGH: "High"}
COLORS = {energy.LOW: "#ececea", energy.MEDIUM: "#fbefc0", energy.HIGH: "#bfe3c0"}
#: The first hour shown, so the grid opens on the working day.
FIRST_VISIBLE_HOUR = 4


class EnergyPanel(QtWidgets.QWidget):
    """Edit the energy profile and read the blocks that do not fit it."""

    changed = pyqtSignal()
    match_requested = pyqtSignal()
    suggest_requested = pyqtSignal()

    def __init__(self, profile: Dict[str, List[int]], parent=None):
        super().__init__(parent)
        self.profile = {a: list(levels) for a, levels in profile.items()}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        intro = QtWidgets.QLabel(
            "Your energy for each kind of writing, hour by hour. Click a cell "
            "to step it through Low, Medium, and High. Generative and editing "
            "blocks in Low hours, and support blocks in your High generative "
            "hours, are listed below.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.grid = QtWidgets.QTableWidget(24, len(energy.ACTIVITIES))
        self.grid.setHorizontalHeaderLabels([a.capitalize() for a in energy.ACTIVITIES])
        self.grid.setVerticalHeaderLabels([f"{h:02d}:00" for h in range(24)])
        self.grid.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.grid.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.grid.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.grid.verticalHeader().setDefaultSectionSize(22)
        self.grid.cellClicked.connect(self.step)
        layout.addWidget(self.grid, 3)

        bar = QtWidgets.QHBoxLayout()
        self.reset_button = QtWidgets.QPushButton("Reset to defaults")
        self.reset_button.setToolTip("Mornings for generative work, late mornings "
                                     "for editing, and afternoons for support")
        self.reset_button.clicked.connect(self.reset)
        self.ratings_button = QtWidgets.QPushButton("From my focus ratings")
        self.ratings_button.setToolTip(
            "Set each hour from the focus ratings of your reviewed blocks, where "
            f"an hour has at least {energy.MIN_REVIEWS} ratings for that activity")
        self.ratings_button.clicked.connect(self.suggest_requested)
        self.match_button = QtWidgets.QPushButton("Match blocks to my energy")
        self.match_button.setToolTip(
            "Propose swaps of equal blocks on the same day that put demanding "
            "work in better hours. Every project keeps its minutes.")
        self.match_button.clicked.connect(self.match_requested)
        for button in (self.reset_button, self.ratings_button, self.match_button):
            bar.addWidget(button)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.report = QtWidgets.QPlainTextEdit()
        self.report.setReadOnly(True)
        layout.addWidget(self.report, 1)
        self._paint()
        self.grid.scrollToItem(self.grid.item(FIRST_VISIBLE_HOUR, 0),
                               QtWidgets.QAbstractItemView.PositionAtTop)

    def _paint(self) -> None:
        for column, activity in enumerate(energy.ACTIVITIES):
            for hour in range(24):
                level = self.profile[activity][hour]
                item = self.grid.item(hour, column)
                if item is None:
                    item = QtWidgets.QTableWidgetItem()
                    self.grid.setItem(hour, column, item)
                item.setText(LABELS[level])
                item.setBackground(QtGui.QBrush(QtGui.QColor(COLORS[level])))
                item.setToolTip(f"{activity.capitalize()} at {hour:02d}:00 is "
                                f"{LABELS[level].lower()}. Click to change it.")

    def level(self, hour: int, activity: str) -> int:
        return self.profile[activity][hour]

    def step(self, hour: int, column: int) -> None:
        """Move one cell to the next level, Low to Medium to High and around."""
        activity = energy.ACTIVITIES[column]
        self.profile[activity][hour] = (self.profile[activity][hour] + 1) % 3
        self._paint()
        self.changed.emit()

    def set_profile(self, profile: Dict[str, List[int]]) -> None:
        self.profile = {a: list(levels) for a, levels in profile.items()}
        self._paint()
        self.changed.emit()

    def reset(self) -> None:
        self.set_profile(energy.default_profile())

    def show_report(self, text: str) -> None:
        self.report.setPlainText(text)
