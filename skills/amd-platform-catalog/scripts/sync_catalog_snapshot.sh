#!/usr/bin/env bash
# Resyncs assets/catalog.json from the canonical catalog/catalog.json.
# Run this after regenerating the canonical catalog -- the skill bundles a
# real copy (not a symlink) so it still works once installed standalone via
# a tool that only fetches this skill's own subdirectory (e.g. `npx skills
# add`), which wouldn't bring along a symlink target outside this directory.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
cp ../../catalog/catalog.json assets/catalog.json
echo "synced assets/catalog.json"
