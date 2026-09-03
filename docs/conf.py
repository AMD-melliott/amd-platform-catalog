"""Sphinx configuration for the AMD Platform Catalog docs site.

Content lives in README.md/PRD.md at the repo root and is pulled in via
MyST `include` directives (whole-file or by section, see
overview.md/bindings/*.md/agent-skill.md) rather than duplicated here, so
the docs site and the in-repo docs can't drift apart.

Uses the furo theme while this is still a personal project -- the
rocm-docs-core ("instinct-design" flavor) setup is preserved on the
`rocm-docs-core-theme` branch to switch back to later.
"""

extensions = ["myst_parser", "sphinx_design"]
myst_enable_extensions = ["colon_fence", "deflist", "linkify"]

project = "AMD Platform Catalog"
copyright = "2026, Matt Elliott"
author = "Matt Elliott"

exclude_patterns = ["_build"]

html_theme = "furo"
html_title = project
