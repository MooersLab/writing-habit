"""Skip the graphical tests cleanly when pytest-qt is not installed.

qtbot and qapp come from pytest-qt, which lives in the ``dev`` extra rather
than ``gui``. A checkout installed with only ``[gui]`` therefore has PyQt5 and
no qtbot, and every test that asks for those fixtures fails at setup with
"fixture 'qtbot' not found". That is a wall of red that says nothing about the
code, so those tests are skipped with a line that names the install to run.
The tests that need no Qt at all still run.
"""
from __future__ import annotations

import pytest

try:
    import pytestqt                                  # noqa: F401
except ImportError:                                  # pragma: no cover
    HAVE_PYTEST_QT = False
else:
    HAVE_PYTEST_QT = True

QT_FIXTURES = {"qtbot", "qapp", "qtmodeltester"}


def pytest_collection_modifyitems(config, items):
    """Mark every test that wants a pytest-qt fixture as skipped."""
    if HAVE_PYTEST_QT:
        return
    skip = pytest.mark.skip(
        reason="pytest-qt is not installed. Run: pip install -e '.[dev]'")
    for item in items:
        if QT_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(skip)
