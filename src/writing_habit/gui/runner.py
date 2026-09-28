"""Run one command off the main thread.

The worker calls :func:`writing_habit.cli.main` with the argument list the form
built, so the interface runs the same code path as the command line rather than
a parallel one. The preview a user sees is therefore not merely equivalent to
what runs; it is what runs.

Two details keep the window honest. The worker never touches a widget, and it
reports through signals, because Qt widgets belong to the thread that created
them. The command prints to ``sys.stdout``, which is process wide, so a module
lock allows one command at a time and the panel disables its run button while a
command is in flight.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import threading
import traceback
from typing import List, Sequence, Tuple

from .qt import QtCore, pyqtSignal

#: Held for the length of a run, because the output capture is process wide.
RUN_LOCK = threading.Lock()


#: The programs the interface drives, and the module holding each ``main``.
PROGRAMS = {
    "writing-habit": "writing_habit.cli",
    "writing-schedule": "writing_schedule.cli",
}


def program_main(prog: str):
    """Return the ``main`` function of ``prog``.

    The lookup is by name rather than by import at module load, because
    ``writing-schedule`` is an optional dependency and the tracker commands must
    keep working without it.
    """
    module_name = PROGRAMS.get(prog)
    if module_name is None:
        raise KeyError(f"unknown program {prog!r}")
    module = importlib.import_module(module_name)
    return module.main


def available(prog: str) -> bool:
    """Return whether ``prog`` can be run in this installation."""
    try:
        program_main(prog)
    except (ImportError, KeyError):
        return False
    return True


def run_sync(argv: Sequence[str], prog: str = "writing-habit") -> Tuple[str, int]:
    """Run one command in this thread and return its output and exit code.

    The tests use this directly, and :class:`CommandWorker` uses it off the main
    thread.  A ``SystemExit`` from argparse becomes the exit code, because a
    graphical program must not exit when a form is incomplete.
    """
    buffer = io.StringIO()
    try:
        main = program_main(prog)
    except (ImportError, KeyError) as exc:
        return f"error: cannot run {prog} ({exc})\n", 1

    with RUN_LOCK:
        try:
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
                code = main(list(argv))
        except SystemExit as exit_:
            code = _exit_code(exit_.code, buffer)
        return buffer.getvalue(), int(code or 0)


def _exit_code(value, buffer: io.StringIO) -> int:
    """Turn the payload of a ``SystemExit`` into an exit code.

    ``sys.exit`` accepts a string as well as a number, and the library uses the
    string form to explain a missing optional dependency.  A string means
    failure and carries the message, so it is written to the captured output
    rather than discarded.  A missing writing-schedule package reaches the user
    this way instead of as a traceback.
    """
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    buffer.write(f"{value}\n")
    return 1


class CommandWorker(QtCore.QThread):
    """Run one command and report the result.

    ``done`` carries the captured output and the exit code.  ``failed`` carries
    a traceback, because an exception that escapes the command is a defect the
    user should be able to copy into an issue rather than a silent no-op.
    """

    done = pyqtSignal(str, int)
    failed = pyqtSignal(str)

    def __init__(self, argv: List[str], prog: str = "writing-habit", parent=None):
        super().__init__(parent)
        self.argv = list(argv)
        self.prog = prog

    def run(self) -> None:                               # pragma: no cover - thread
        try:
            output, code = run_sync(self.argv, self.prog)
        except Exception:                                 # noqa: BLE001
            self.failed.emit(traceback.format_exc())
        else:
            self.done.emit(output, code)
