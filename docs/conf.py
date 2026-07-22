"""Sphinx configuration for the writing-habit documentation."""

from __future__ import annotations

import importlib.metadata as _metadata

# -- Project information ------------------------------------------------------

project = "writing-habit"
author = "Blaine Mooers"
copyright = "2026, Blaine Mooers"

try:
    release = _metadata.version("writing-habit")
except _metadata.PackageNotFoundError:  # not installed, for example a bare checkout
    release = "0.1.0"
version = ".".join(release.split(".")[:2])

# -- General configuration ----------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "myst_parser",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# _diagrams holds the DOT sources for the images, not documentation pages.
exclude_patterns = ["_build", "_diagrams", "Thumbs.db", ".DS_Store"]

# -- Autodoc and Napoleon -----------------------------------------------------

autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
napoleon_google_docstring = True
napoleon_numpy_docstring = True
# Render class "Attributes" sections as :ivar: fields rather than as separate
# attribute directives, so they do not collide with the attributes autodoc
# already documents for a dataclass.
napoleon_use_ivar = True

# -- MyST ---------------------------------------------------------------------

myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

# -- HTML output --------------------------------------------------------------

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_title = f"writing-habit {release}"
