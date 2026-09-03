"""Sphinx configuration for the AMD Platform Catalog docs site.

Content lives in README.md/PRD.md at the repo root (symlinked into this
directory) rather than duplicated here, so the docs site and the
in-repo docs can't drift apart.
"""

project = "AMD Platform Catalog"
copyright = "2026, Matt Elliott"
author = "Matt Elliott"

extensions = ["myst_parser"]
myst_enable_extensions = ["colon_fence", "deflist", "linkify"]

root_doc = "index"
source_suffix = {".md": "markdown"}

exclude_patterns = ["_build"]

html_theme = "furo"
html_title = project
