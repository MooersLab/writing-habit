"""The review panel: a block's objectives before it starts, its review after.

The panel sits on the right of the hour picker, and in the Review dialog the
Schedule tab opens for the selected block. It has three parts.

Objectives
    One to three things the block is for, each checked off when met. They are
    written to the database as soon as they change, because they are the plan
    for the block. A task can come from the grasscatcher list and go back to it.

Review
    Focus from 1 to 5, a tally of interruptions, output, a next-step note, and
    a note. The counts of objectives committed and met come from the list when
    it has items and are typed by hand when it has none. Save review writes
    them.

Debrief
    A short coaching note from a model served on this computer, or a plain
    summary written without one. See :mod:`writing_habit.debrief`.

Everything is keyed by the block's day, start, and project code, as
:mod:`writing_habit.review` describes, so track sync never touches it.
"""

from __future__ import annotations

import datetime as _dt
from contextlib import contextmanager
from typing import Optional

from .. import db, debrief as debriefmod, review
from ..project_lists import GRASSCATCHER, Entry
from . import settings
from .qt import Qt, QtGui, QtWidgets, pyqtSignal

#: The text a spin box shows for a field left blank.
BLANK = "not rated"


def block_text(block, table=None) -> str:
    """Return ``B 05:00-07:00 1006AIrxOpt`` for a block."""
    name = ""
    if table is not None:
        info = table.project_info(block.letter) or {}
        name = info.get("name") or ""
    return f"{block.letter} {block.start}-{block.end} {name}".rstrip()


class ReviewPanel(QtWidgets.QWidget):
    """Objectives, review, and debrief for the blocks of one hour or one cell."""

    #: Emitted when the panel changed the weekly table (the grasscatcher list).
    table_edited = pyqtSignal()
    logged = pyqtSignal(str)

    def __init__(self, table, monday: Optional[_dt.date], blocks: list,
                 db_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.table = table
        self.monday = monday
        self.blocks = list(blocks)
        self.db_path = db_path if db_path is not None else settings.get("db")
        #: Asks the model.  A test replaces it to answer without a server.
        self.ask = debriefmod.debrief
        self._loading = False
        self._shown: Optional[review.Review] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 0, 0, 0)
        title = QtWidgets.QLabel("<b>Objectives and review</b>")
        layout.addWidget(title)

        self.problem = QtWidgets.QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)

        self.body = QtWidgets.QWidget()
        body = QtWidgets.QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.body, 1)

        pick = QtWidgets.QHBoxLayout()
        pick.addWidget(QtWidgets.QLabel("Block"))
        self.block_box = QtWidgets.QComboBox()
        for block in self.blocks:
            self.block_box.addItem(block_text(block, table))
        pick.addWidget(self.block_box, 1)
        body.addLayout(pick)

        self.last_label = QtWidgets.QLabel()
        self.last_label.setWordWrap(True)
        self.last_label.setStyleSheet("color: #52514e;")
        body.addWidget(self.last_label)

        # -- objectives
        group = QtWidgets.QGroupBox("Objectives for this block")
        objectives = QtWidgets.QVBoxLayout(group)
        self.objective_list = QtWidgets.QListWidget()
        self.objective_list.setMaximumHeight(110)
        self.objective_list.itemChanged.connect(self._item_changed)
        objectives.addWidget(self.objective_list)
        add_row = QtWidgets.QHBoxLayout()
        self.objective_edit = QtWidgets.QLineEdit()
        self.objective_edit.setPlaceholderText("Draft the second aim paragraph")
        self.objective_edit.returnPressed.connect(lambda: self.add_objective())
        self.add_button = QtWidgets.QPushButton("Add")
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(lambda: self.add_objective())
        add_row.addWidget(self.objective_edit, 1)
        add_row.addWidget(self.add_button)
        objectives.addLayout(add_row)
        tools = QtWidgets.QHBoxLayout()
        self.park_button = QtWidgets.QPushButton("Back to grasscatcher")
        self.park_button.setAutoDefault(False)
        self.park_button.setToolTip(
            "Take the selected objective off this block and keep it on the "
            "grasscatcher list for later")
        self.park_button.clicked.connect(lambda: self.park_objective())
        self.remove_button = QtWidgets.QPushButton("Remove")
        self.remove_button.setAutoDefault(False)
        self.remove_button.clicked.connect(lambda: self.remove_objective())
        tools.addWidget(self.park_button)
        tools.addWidget(self.remove_button)
        tools.addStretch(1)
        objectives.addLayout(tools)
        catch = QtWidgets.QHBoxLayout()
        self.catch_box = QtWidgets.QComboBox()
        self.catch_box.setToolTip("Tasks waiting on the grasscatcher list")
        self.commit_button = QtWidgets.QPushButton("Commit")
        self.commit_button.setAutoDefault(False)
        self.commit_button.setToolTip(
            "Make the chosen grasscatcher task an objective of this block")
        self.commit_button.clicked.connect(lambda: self.commit_from_grasscatcher())
        catch.addWidget(QtWidgets.QLabel("From grasscatcher"))
        catch.addWidget(self.catch_box, 1)
        catch.addWidget(self.commit_button)
        objectives.addLayout(catch)
        self.limit_label = QtWidgets.QLabel()
        self.limit_label.setWordWrap(True)
        self.limit_label.setStyleSheet("color: #8a5a00;")
        objectives.addWidget(self.limit_label)
        body.addWidget(group)

        # -- review
        group = QtWidgets.QGroupBox("Review when the block ends")
        form = QtWidgets.QFormLayout(group)
        counts = QtWidgets.QHBoxLayout()
        self.met_spin = QtWidgets.QSpinBox()
        self.met_spin.setRange(-1, 20)
        self.met_spin.setSpecialValueText("-")
        self.committed_spin = QtWidgets.QSpinBox()
        self.committed_spin.setRange(-1, 20)
        self.committed_spin.setSpecialValueText("-")
        counts.addWidget(self.met_spin)
        counts.addWidget(QtWidgets.QLabel("of"))
        counts.addWidget(self.committed_spin)
        counts.addStretch(1)
        form.addRow("Objectives met", counts)
        self.focus_spin = QtWidgets.QSpinBox()
        self.focus_spin.setRange(0, 5)
        self.focus_spin.setSpecialValueText(BLANK)
        self.focus_spin.setToolTip("How focused you stayed, from 1 (scattered) "
                                   "to 5 (absorbed)")
        form.addRow("Focus, 1 to 5", self.focus_spin)
        tally = QtWidgets.QHBoxLayout()
        self.interruption_spin = QtWidgets.QSpinBox()
        self.interruption_spin.setRange(-1, 999)
        self.interruption_spin.setSpecialValueText("-")
        self.tally_button = QtWidgets.QPushButton("+1")
        self.tally_button.setAutoDefault(False)
        self.tally_button.setToolTip("Count one interruption")
        self.tally_button.clicked.connect(
            lambda: self.interruption_spin.setValue(
                max(self.interruption_spin.value(), 0) + 1))
        tally.addWidget(self.interruption_spin)
        tally.addWidget(self.tally_button)
        tally.addStretch(1)
        form.addRow("Interruptions", tally)
        self.output_edit = QtWidgets.QLineEdit()
        self.output_edit.setPlaceholderText("600 words, figure 2, 3 papers read")
        form.addRow("Output", self.output_edit)
        self.next_edit = QtWidgets.QLineEdit()
        self.next_edit.setPlaceholderText("Where to start next time")
        form.addRow("Next step", self.next_edit)
        self.note_edit = QtWidgets.QLineEdit()
        form.addRow("Note", self.note_edit)
        body.addWidget(group)

        # -- debrief
        group = QtWidgets.QGroupBox("Debrief")
        debrief_layout = QtWidgets.QVBoxLayout(group)
        row = QtWidgets.QHBoxLayout()
        self.model_box = QtWidgets.QCheckBox("Ask the local model")
        self.model_box.setToolTip(
            f"Send this review to the model {settings.get('ai_model')} at "
            f"{settings.get('ai_url')}, on this computer. Off, the debrief is a "
            "plain summary written without a model, and nothing leaves the app.")
        self.model_box.setChecked(settings.get("ai_debrief") == "true")
        self.model_box.toggled.connect(
            lambda on: settings.put("ai_debrief", "true" if on else "false"))
        self.debrief_button = QtWidgets.QPushButton("Debrief")
        self.debrief_button.setAutoDefault(False)
        self.debrief_button.clicked.connect(lambda: self.run_debrief())
        row.addWidget(self.model_box)
        row.addStretch(1)
        row.addWidget(self.debrief_button)
        debrief_layout.addLayout(row)
        self.debrief_view = QtWidgets.QPlainTextEdit()
        self.debrief_view.setReadOnly(True)
        self.debrief_view.setMaximumHeight(90)
        debrief_layout.addWidget(self.debrief_view)
        self.source_label = QtWidgets.QLabel()
        self.source_label.setStyleSheet("color: #898781;")
        self.source_label.setWordWrap(True)
        debrief_layout.addWidget(self.source_label)
        body.addWidget(group)

        save_row = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel()
        self.save_button = QtWidgets.QPushButton("Save review")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(lambda: self.save())
        save_row.addWidget(self.status, 1)
        save_row.addWidget(self.save_button)
        body.addLayout(save_row)

        self.block_box.currentIndexChanged.connect(lambda _i: self.load())
        self.objective_list.currentRowChanged.connect(lambda _r: self._update_buttons())
        self._check_ready()
        self.load()

    # -- state -------------------------------------------------------------
    def _check_ready(self) -> None:
        problem = None
        if not self.blocks:
            problem = ("Place a block first. Its objectives and review then "
                       "appear here.")
        elif not self.db_path:
            problem = ("Choose the habit database in the Plan or Track form, "
                       "so objectives and reviews have somewhere to go.")
        elif self.monday is None:
            problem = "The table's file name gives no week, so the blocks have no dates."
        self.problem.setText(problem or "")
        self.problem.setVisible(problem is not None)
        self.body.setEnabled(problem is None)

    def ready(self) -> bool:
        return self.body.isEnabled()

    def block(self):
        index = self.block_box.currentIndex()
        return self.blocks[index] if 0 <= index < len(self.blocks) else None

    def key(self) -> Optional[review.BlockKey]:
        block = self.block()
        if block is None or self.monday is None:
            return None
        return review.BlockKey.for_block(self.monday, block)

    @contextmanager
    def connection(self):
        con = db.connect(self.db_path)
        try:
            review.ensure(con)
            yield con
        finally:
            con.close()

    # -- loading -----------------------------------------------------------
    def load(self) -> None:
        """Show the stored objectives and review of the chosen block."""
        self._fill_grasscatcher()
        if not self.ready():
            self._update_buttons()
            return
        key = self.key()
        with self.connection() as con:
            items = review.objectives(con, key)
            stored = review.review(con, key)
            last = review.last_next_step(con, key.code, key)
        self._loading = True
        self.objective_list.clear()
        for item in items:
            row = QtWidgets.QListWidgetItem(item.text)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            row.setCheckState(Qt.Checked if item.done else Qt.Unchecked)
            row.setData(Qt.UserRole, item.objective_id)
            self.objective_list.addItem(row)
        self.committed_spin.setValue(-1 if stored.objectives_committed is None
                                     else stored.objectives_committed)
        self.met_spin.setValue(-1 if stored.objectives_met is None
                               else stored.objectives_met)
        self.focus_spin.setValue(stored.focus or 0)
        self.interruption_spin.setValue(-1 if stored.interruptions is None
                                        else stored.interruptions)
        self.output_edit.setText(stored.output_units or "")
        self.next_edit.setText(stored.next_step or "")
        self.note_edit.setText(stored.note or "")
        self.debrief_view.setPlainText(stored.debrief or "")
        self.source_label.setText("")
        self.last_label.setText(f"Last time you planned to start with: {last}"
                                if last else "")
        self.last_label.setVisible(bool(last))
        self.status.setText(f"Saved {stored.updated_at}" if stored.updated_at else "")
        self._loading = False
        self._shown = self.current()
        self._sync_counts()
        self._update_buttons()

    def _fill_grasscatcher(self) -> None:
        self.catch_box.clear()
        if self.table is None:
            return
        block = self.block()
        entries = self.table.lists.entries(GRASSCATCHER)
        # The tasks of this block's project come first.
        order = sorted(range(len(entries)), key=lambda i: (
            0 if block is not None and entries[i].code == block.letter else 1, i))
        for position in order:
            entry = entries[position]
            head = f"{entry.code}: " if entry.code else ""
            self.catch_box.addItem(head + entry.description, position)

    def _sync_counts(self) -> None:
        """Follow the list in the two counts, or free them when it is empty."""
        count = self.objective_list.count()
        manual = count == 0
        self.committed_spin.setEnabled(manual)
        self.met_spin.setEnabled(manual)
        if not manual:
            done = sum(1 for i in range(count)
                       if self.objective_list.item(i).checkState() == Qt.Checked)
            self.committed_spin.setValue(count)
            self.met_spin.setValue(done)
        self.limit_label.setText(
            f"{count} objectives. Three or fewer keep the block winnable; park "
            "the rest on the grasscatcher." if count > review.OBJECTIVE_LIMIT else "")
        self.limit_label.setVisible(count > review.OBJECTIVE_LIMIT)

    def _update_buttons(self) -> None:
        selected = self.objective_list.currentItem() is not None
        ready = self.ready()
        self.park_button.setEnabled(ready and selected and self.table is not None)
        self.remove_button.setEnabled(ready and selected)
        self.commit_button.setEnabled(ready and self.catch_box.count() > 0)

    # -- objectives ----------------------------------------------------------
    def add_objective(self, text: Optional[str] = None, origin: str = "typed"):
        """Add an objective to the block.  Return its id, or ``None``."""
        text = (self.objective_edit.text() if text is None else text).strip()
        if not text or not self.ready():
            return None
        with self.connection() as con:
            objective_id = review.add_objective(con, self.key(), text, origin)
        if origin == "typed":
            self.objective_edit.clear()
        self.load()
        return objective_id

    def _selected_id(self) -> Optional[int]:
        item = self.objective_list.currentItem()
        return None if item is None else int(item.data(Qt.UserRole))

    def _item_changed(self, item) -> None:
        if self._loading or not self.ready():
            return
        objective_id = int(item.data(Qt.UserRole))
        with self.connection() as con:
            review.mark(con, objective_id, item.checkState() == Qt.Checked)
            text = item.text().strip()
            if text:
                review.edit_objective(con, objective_id, text)
        self._sync_counts()

    def remove_objective(self) -> Optional[review.Objective]:
        objective_id = self._selected_id()
        if objective_id is None:
            return None
        with self.connection() as con:
            gone = review.remove_objective(con, objective_id)
        self.load()
        return gone

    def park_objective(self) -> Optional[int]:
        """Move the selected objective to the grasscatcher.  Return its position."""
        gone = self.remove_objective()
        if gone is None or self.table is None:
            return None
        block = self.block()
        position = self.table.lists.insert(
            GRASSCATCHER, None, Entry(block.letter if block else None, gone.text))
        self.table.dirty = True
        self.table_edited.emit()
        self.logged.emit(f"Parked “{gone.text}” on the grasscatcher")
        self._fill_grasscatcher()
        self._update_buttons()
        return position

    def commit_from_grasscatcher(self, position: Optional[int] = None):
        """Make a grasscatcher task an objective of this block.  Return its id."""
        if position is None:
            position = self.catch_box.currentData()
        if position is None or self.table is None or not self.ready():
            return None
        entry = self.table.lists.entries(GRASSCATCHER)[position]
        objective_id = self.add_objective(entry.description, origin="grasscatcher")
        if objective_id is None:
            return None
        self.table.lists.remove(GRASSCATCHER, position)
        self.table.dirty = True
        self.table_edited.emit()
        self.logged.emit(f"Committed “{entry.description}” to {self.key().code} "
                         f"{self.key().start}")
        self.load()
        return objective_id

    # -- review ----------------------------------------------------------------
    def current(self) -> review.Review:
        """Return the review the fields show."""
        def number(spin, blank):
            return None if spin.value() == blank else spin.value()
        return review.Review(
            objectives_committed=number(self.committed_spin, -1),
            objectives_met=number(self.met_spin, -1),
            focus=number(self.focus_spin, 0),
            interruptions=number(self.interruption_spin, -1),
            output_units=self.output_edit.text().strip() or None,
            next_step=self.next_edit.text().strip() or None,
            note=self.note_edit.text().strip() or None,
            debrief=self.debrief_view.toPlainText().strip() or None,
        )

    def save(self) -> Optional[review.Review]:
        """Write the review.  Return what was stored, or ``None`` when refused."""
        if not self.ready():
            return None
        try:
            with self.connection() as con:
                stored = review.save_review(con, self.key(), self.current())
        except ValueError as exc:
            self.status.setText(str(exc))
            return None
        self.status.setText("Saved")
        self._shown = self.current()
        block = self.block()
        self.logged.emit(f"Saved the review of {block.letter} {block.start} "
                         f"on {self.key().day}")
        return stored

    def save_if_changed(self) -> Optional[review.Review]:
        """Save when a field differs from what was loaded, as a window closes."""
        if not self.ready() or getattr(self, "_shown", None) is None:
            return None
        if self.current() == self._shown:
            return None
        return self.save()

    def facts(self) -> debriefmod.BlockFacts:
        block = self.block()
        info = (self.table.project_info(block.letter) or {}) if self.table else {}
        value = self.current()
        items = [(self.objective_list.item(i).text(),
                  self.objective_list.item(i).checkState() == Qt.Checked)
                 for i in range(self.objective_list.count())]
        return debriefmod.BlockFacts(
            project=info.get("name") or block.letter, minutes=block.minutes,
            objectives=items, committed=value.objectives_committed,
            met=value.objectives_met, focus=value.focus,
            interruptions=value.interruptions, output_units=value.output_units,
            next_step=value.next_step, note=value.note)

    def run_debrief(self) -> Optional[str]:
        """Write the debrief into the panel and save it with the review."""
        if not self.ready():
            return None
        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(Qt.WaitCursor))
        try:
            text, source = self.ask(self.facts(), self.model_box.isChecked(),
                                    model=settings.get("ai_model"),
                                    url=settings.get("ai_url"))
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.debrief_view.setPlainText(text)
        self.source_label.setText(f"Written by the {source}.")
        self.save()
        return text


class ReviewDialog(QtWidgets.QDialog):
    """The review panel on its own, for the block selected in the grid."""

    def __init__(self, table, monday, blocks, db_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Objectives and review")
        layout = QtWidgets.QVBoxLayout(self)
        self.panel = ReviewPanel(table, monday, blocks, db_path, self)
        layout.addWidget(self.panel)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)

    def done(self, result) -> None:
        self.panel.save_if_changed()
        super().done(result)
