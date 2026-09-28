"""The web pages the Help buttons open, with no Qt.

The addresses live in one place so a later move, such as publishing the Sphinx
site on Read the Docs, changes one line. Until that site exists, the
documentation button opens the interface page of the documentation as GitHub
renders it, which shows the same text and screenshots.
"""

from __future__ import annotations

#: The repository on GitHub, and the branch whose files the buttons open.
REPOSITORY = "https://github.com/MooersLab/writing-habit"
BRANCH = "main"

#: The README as GitHub renders it.
README_URL = f"{REPOSITORY}/blob/{BRANCH}/README.md"

#: The documentation of the interface. Replace this with the Read the Docs
#: address, for example ``https://writing-habit-py.readthedocs.io/en/latest/gui.html``,
#: once that site is published.
DOCS_URL = f"{REPOSITORY}/blob/{BRANCH}/docs/gui.md"
