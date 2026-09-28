"""Open the weekly table in the writer's own text editor, with no Qt.

The editor is named by the ``WHGEDITOR`` variable. The process environment is
read first, because a window started from a shell has already sourced the
shell's start-up file. A window started from the Dock or Finder has not, so
``~/.bashrc`` is then read directly for a line such as::

    export WHGEDITOR="emacsclient -n"

When neither names an editor, the operating system's default text editor opens
the file (``open -t`` on macOS, ``xdg-open`` on Linux, the file association on
Windows).

The value may carry arguments, and the file path is appended as the last one.
The module imports Qt nowhere, so its tests run wherever the package runs.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

VARIABLE = "WHGEDITOR"

#: Folders a window started from the Dock does not have on its ``PATH``, where
#: Homebrew and MacPorts put editors such as ``emacsclient``.
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")

_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?" + VARIABLE + r"=(?P<value>.*)$")


def default_bashrc() -> Path:
    return Path.home() / ".bashrc"


def read_bashrc_value(path: Optional[Path] = None,
                      name: str = VARIABLE) -> Optional[str]:
    """Return the value the start-up file assigns to ``name``, or ``None``.

    The last assignment wins, as it would when the shell sources the file. A
    quoted value keeps its spaces, a trailing comment is dropped, and ``$HOME``
    and ``~`` are expanded. An empty value counts as no value.
    """
    path = Path(path) if path is not None else default_bashrc()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    pattern = _ASSIGNMENT if name == VARIABLE else re.compile(
        r"^\s*(?:export\s+)?" + re.escape(name) + r"=(?P<value>.*)$")
    found: Optional[str] = None
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        try:
            words = shlex.split(match.group("value"), comments=True)
        except ValueError:                  # an unbalanced quote
            continue
        value = " ".join(words).strip()
        found = value or None
    if found is None:
        return None
    return os.path.expanduser(os.path.expandvars(found))


def configured_editor(environ: Optional[Mapping[str, str]] = None,
                      bashrc: Optional[Path] = None) -> Tuple[Optional[str], str]:
    """Return ``(editor command or None, where it came from)``."""
    environ = os.environ if environ is None else environ
    value = (environ.get(VARIABLE) or "").strip()
    if value:
        return value, "the environment"
    value = read_bashrc_value(bashrc)
    if value:
        where = str(bashrc) if bashrc is not None else "~/.bashrc"
        return value, where
    return None, "the system default"


def _resolve(program: str) -> str:
    """Return ``program`` as a full path when it can be found, else unchanged."""
    if os.sep in program:
        return program
    search = os.pathsep.join(
        [os.environ.get("PATH", "")] + [p for p in EXTRA_PATH if os.path.isdir(p)])
    return shutil.which(program, path=search) or program


def editor_command(path: str, environ: Optional[Mapping[str, str]] = None,
                   bashrc: Optional[Path] = None,
                   platform: Optional[str] = None) -> Tuple[List[str], str]:
    """Return ``(argv, source)`` that opens ``path`` in the chosen editor.

    On Windows with no editor named, ``argv`` is empty and the caller should
    use :func:`os.startfile`.
    """
    platform = platform or sys.platform
    command, source = configured_editor(environ, bashrc)
    if command:
        argv = shlex.split(command)
        if argv:
            argv[0] = _resolve(argv[0])
            return argv + [str(path)], source
    if platform == "darwin":
        return ["open", "-t", str(path)], source
    if platform.startswith("win"):
        return [], source
    return ["xdg-open", str(path)], source


def open_in_editor(path: str, environ: Optional[Mapping[str, str]] = None,
                   bashrc: Optional[Path] = None) -> Tuple[List[str], str]:
    """Start the editor on ``path`` without waiting for it.  Return what ran.

    The editor runs in its own session, so closing the window does not close
    the editor. Raises ``OSError`` when the program cannot be started.
    """
    argv, source = editor_command(path, environ, bashrc)
    if not argv:
        os.startfile(str(path))                # type: ignore[attr-defined]
        return ["startfile", str(path)], source
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return argv, source
