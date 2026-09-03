"""Sphinx configuration for the AMD Platform Catalog docs site.

Built on rocm-docs-core (https://github.com/ROCm/rocm-docs-core), using its
"instinct-design" theme flavor. Content lives in README.md/PRD.md at the
repo root and is pulled in via MyST `include` directives (whole-file or by
section, see overview.md/bindings/*.md/agent-skill.md) rather than
duplicated here, so the docs site and the in-repo docs can't drift apart.
"""

extensions = ["rocm_docs"]
html_theme = "rocm_docs_theme"
html_theme_options = {"flavor": "instinct-design"}

external_toc_path = "./sphinx/_toc.yml"

# This is a standalone project, not part of the ROCm docs family -- skip
# rocm_docs' cross-project intersphinx linking (avoids both a "current
# project not found in projects.yaml" warning we can't clear, since we're
# genuinely not in that registry, and a slow/flaky round of network fetches
# against dozens of ROCm projects' inventories on every build).
external_projects = []
external_projects_remote_repository = ""

project = "AMD Platform Catalog"
copyright = "2026, Matt Elliott"
author = "Matt Elliott"
version = "0.1.0"
release = "0.1.0"
html_title = project

exclude_patterns = ["_build"]
