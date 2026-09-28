"""One argparse option to one widget.

The rule that picks a widget reads the primary flag first and the shape of the
action second. Reading the flag matters, because two options can share a dest
while meaning different things. ``writing-habit history --from`` and
``writing-habit track add --start`` both carry the dest ``start``, yet one is a
date and the other is a clock time.

Every field answers :meth:`Field.value`, which returns the string the command
line expects, or ``None`` when the option is to be omitted. An optional field
whose widget has no natural empty state, such as a date or a count, carries a
small check box that decides whether it is sent at all.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional

from .argspec import OptionSpec
from .qt import Qt, QtCore, QtWidgets

#: Flags whose value is a calendar date.
DATE_FLAGS = {"--week", "--day", "--from", "--to"}
#: Flags whose value is a clock time.
TIME_FLAGS = {"--start", "--end"}
#: Flags that name a directory.
DIR_FLAGS = {"--dir"}
#: Flags that name a file to write, which may not exist yet.
SAVE_FLAGS = {"--out", "--plot", "--db"}
#: Flags and positional dests that name a file to read.
OPEN_FLAGS = {"--table"}
OPEN_DESTS = {"path", "table"}

#: Values the schema or the documented vocabulary expects, offered as
#: suggestions in an editable box. The parser declares no ``choices`` for these,
#: because the command line accepts any string and the database enforces the
#: check, so the interface suggests rather than restricts.
SUGGESTED = {
    "--category": ("generative", "editing", "support"),
    "--tag": ("teaching", "meeting", "data-collection", "travel", "grant",
              "normal"),
}

#: Flags whose empty value means something. ``writing-schedule --tz ""`` asks
#: for floating times, so the field must be able to send an empty string.
SEND_EMPTY_FLAGS = {"--tz"}

ISO = "yyyy-MM-dd"
CLOCK = "HH:mm"


class Field:
    """Base class: a labelled row that yields one command-line value."""

    def __init__(self, spec: OptionSpec):
        self.spec = spec
        self.widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QHBoxLayout(self.widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self._changed = []

    # -- API ---------------------------------------------------------------
    def value(self) -> Optional[object]:
        raise NotImplementedError

    def set_value(self, value) -> None:
        raise NotImplementedError

    def on_change(self, slot) -> None:
        self._changed.append(slot)

    def _notify(self, *_args) -> None:
        for slot in self._changed:
            slot()

    def _add(self, widget) -> None:
        self.layout.addWidget(widget)
        if self.spec.help:
            widget.setToolTip(self.spec.help)


class FlagField(Field):
    """A ``store_true`` option, such as ``--strict``."""

    def __init__(self, spec):
        super().__init__(spec)
        self.box = QtWidgets.QCheckBox(spec.help or spec.label)
        self.box.stateChanged.connect(self._notify)
        self._add(self.box)
        self.layout.addStretch(1)

    def value(self):
        return self.box.isChecked()

    def set_value(self, value):
        self.box.setChecked(bool(value))


class ChoiceField(Field):
    """An option with ``choices``, such as ``--format``."""

    def __init__(self, spec):
        super().__init__(spec)
        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(list(spec.choices or ()))
        self.combo.currentIndexChanged.connect(self._notify)
        self._add(self.combo)
        self.layout.addStretch(1)

    def value(self):
        return self.combo.currentText()

    def set_value(self, value):
        index = self.combo.findText(str(value))
        if index >= 0:
            self.combo.setCurrentIndex(index)


class _Optional(Field):
    """A field whose widget always shows something, so it needs an on switch."""

    def __init__(self, spec):
        super().__init__(spec)
        self.include = None
        if not spec.required:
            self.include = QtWidgets.QCheckBox("send")
            self.include.setToolTip("Include this option in the command")
            self.include.stateChanged.connect(self._on_toggle)

    def _finish(self) -> None:
        if self.include is not None:
            self.layout.addWidget(self.include)
            self._on_toggle()
        self.layout.addStretch(1)

    def _on_toggle(self, *_args) -> None:
        if self.include is not None:
            self.editor.setEnabled(self.include.isChecked())
        self._notify()

    def _sending(self) -> bool:
        return self.include is None or self.include.isChecked()


class DateField(_Optional):
    """A calendar date, with a button for today."""

    def __init__(self, spec):
        super().__init__(spec)
        self.editor = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.editor.setCalendarPopup(True)
        self.editor.setDisplayFormat(ISO)
        self.editor.dateChanged.connect(self._notify)
        self._add(self.editor)
        today = QtWidgets.QPushButton("Today")
        today.clicked.connect(self._today)
        self.layout.addWidget(today)
        self._finish()

    def _today(self) -> None:
        self.editor.setDate(QtCore.QDate.currentDate())
        if self.include is not None:
            self.include.setChecked(True)
        self._notify()

    def value(self):
        if not self._sending():
            return None
        return self.editor.date().toString(ISO)

    def set_value(self, value):
        if not value:
            return
        date = QtCore.QDate.fromString(str(value), ISO)
        if date.isValid():
            self.editor.setDate(date)
            if self.include is not None:
                self.include.setChecked(True)


class TimeField(_Optional):
    """A clock time, such as the start of a session."""

    def __init__(self, spec):
        super().__init__(spec)
        self.editor = QtWidgets.QTimeEdit(QtCore.QTime(9, 0))
        self.editor.setDisplayFormat(CLOCK)
        self.editor.timeChanged.connect(self._notify)
        self._add(self.editor)
        self._finish()

    def value(self):
        if not self._sending():
            return None
        return self.editor.time().toString(CLOCK)

    def set_value(self, value):
        time = QtCore.QTime.fromString(str(value), CLOCK)
        if time.isValid():
            self.editor.setTime(time)
            if self.include is not None:
                self.include.setChecked(True)


class IntField(_Optional):
    """A whole number, such as the minutes of a session."""

    def __init__(self, spec):
        super().__init__(spec)
        self.editor = QtWidgets.QSpinBox()
        self.editor.setRange(0, 10_000)
        self.editor.setValue(90)
        self.editor.valueChanged.connect(self._notify)
        self._add(self.editor)
        self._finish()

    def value(self):
        if not self._sending():
            return None
        return str(self.editor.value())

    def set_value(self, value):
        try:
            self.editor.setValue(int(value))
        except (TypeError, ValueError):
            return
        if self.include is not None:
            self.include.setChecked(True)


class SuggestionField(Field):
    """A free-text value with the usual values offered in a drop-down.

    The command line accepts any string here, and the database enforces its own
    check, so the box stays editable and an empty box omits the option.
    """

    def __init__(self, spec, suggestions):
        super().__init__(spec)
        self.combo = QtWidgets.QComboBox()
        self.combo.setEditable(True)
        self.combo.addItem("")
        self.combo.addItems(list(suggestions))
        self.combo.setCurrentText("")
        self.combo.currentTextChanged.connect(self._notify)
        self._add(self.combo)
        self.layout.addStretch(1)

    def value(self):
        return self.combo.currentText().strip() or None

    def set_value(self, value):
        self.combo.setCurrentText("" if value is None else str(value))


class TextField(Field):
    """A free-text value.  An empty line edit omits the option."""

    def __init__(self, spec):
        super().__init__(spec)
        self.editor = QtWidgets.QLineEdit()
        self.editor.setPlaceholderText(spec.help)
        self.editor.textChanged.connect(self._notify)
        self._add(self.editor)

    def value(self):
        return self.editor.text().strip() or None

    def set_value(self, value):
        self.editor.setText("" if value is None else str(value))


class SendableTextField(_Optional):
    """Free text that can be sent even when it is empty.

    ``writing-schedule --tz ""`` selects floating calendar times, which a plain
    line edit could never express, because an empty line edit means "leave the
    option out". The check box separates the two.
    """

    def __init__(self, spec):
        super().__init__(spec)
        self.editor = QtWidgets.QLineEdit()
        self.editor.setPlaceholderText(spec.help)
        self.editor.textChanged.connect(self._notify)
        self._add(self.editor)
        self._finish()

    def value(self):
        if not self._sending():
            return None
        return self.editor.text().strip()

    def set_value(self, value):
        if value is None:
            return
        self.editor.setText(str(value))
        if self.include is not None:
            self.include.setChecked(True)


class PathField(TextField):
    """A file or directory, with a chooser beside the line edit."""

    def __init__(self, spec, mode: str = "open", filter: str = "All files (*)"):
        super().__init__(spec)
        self.mode = mode
        self.filter = filter
        button = QtWidgets.QPushButton("Browse")
        button.clicked.connect(self.browse)
        self.layout.addWidget(button)
        self.button = button

    def browse(self) -> None:
        start = self.editor.text() or ""
        if self.mode == "dir":
            path = QtWidgets.QFileDialog.getExistingDirectory(
                self.widget, f"Choose {self.spec.label}", start)
        elif self.mode == "save":
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self.widget, f"Choose {self.spec.label}", start, self.filter,
                options=QtWidgets.QFileDialog.DontConfirmOverwrite)
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self.widget, f"Choose {self.spec.label}", start, self.filter)
        if path:
            self.editor.setText(path)


def build(spec: OptionSpec) -> Field:
    """Return the field for ``spec``, following the rule in the module docstring."""
    flag = spec.flag
    if spec.is_flag:
        return FlagField(spec)
    if spec.choices:
        return ChoiceField(spec)
    if flag in SUGGESTED:
        return SuggestionField(spec, SUGGESTED[flag])
    if flag in SEND_EMPTY_FLAGS:
        return SendableTextField(spec)
    if flag in DATE_FLAGS:
        return DateField(spec)
    if flag in TIME_FLAGS:
        return TimeField(spec)
    if flag in DIR_FLAGS:
        return PathField(spec, mode="dir")
    if flag == "--db":
        return PathField(spec, mode="save", filter="SQLite database (*.db);;All files (*)")
    if flag in SAVE_FLAGS:
        return PathField(spec, mode="save")
    if flag in OPEN_FLAGS or (spec.positional and spec.dest in OPEN_DESTS):
        return PathField(spec, mode="open", filter="Org and data files (*.org *.csv *.ics);;All files (*)")
    if spec.is_int:
        return IntField(spec)
    return TextField(spec)


def today_iso() -> str:
    """Return today as an ISO date, which seeds the week and day fields."""
    return _dt.date.today().isoformat()
