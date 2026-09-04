# Contributing

Thanks for looking at this project. It's a young, personal-account repo (see
`PRD.md` §10 on long-term ownership), so contributions are welcome, but the
process is still lightweight.

## Before you start

- `PRD.md` has the full design: problem statement, data model, sourcing
  decisions, and the phased implementation plan. Read it before proposing a
  schema change or a new data source.
- `README.md` covers how to build the catalog, run the tests, and use each
  language binding.

## Setting up

Requires [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run python -m tools.catalog_build.build_catalog --output catalog/catalog.json
uv run python -m tools.catalog_build.validate_schema catalog/catalog.json
```

Pass `--fixtures-dir tests/fixtures` to build offline from the pinned
snapshots the test suite uses, instead of fetching all five sources live.

## Kinds of changes

**Catalog data.** Most fields in `catalog.json` are mechanically parsed from
an upstream source (see `PRD.md` §5) and shouldn't be hand-edited. If a value
looks wrong, the fix usually belongs in an ingestion script
(`tools/catalog_build/`) or in the upstream source itself, not in
`catalog.json` directly.

**Hand-validated notes.** The one exception is `catalog/notes.json`: a small,
explicitly separate overlay for facts that only come from running on real
hardware (see `PRD.md` §6.5). A new note needs a `device_id`, the `field` it
corrects or annotates, a `note` explaining what was observed and why, and
`validated_on`. Add `validated_by` if you can say what hardware or tool
confirmed it. Notes are hand-authored, so expect more scrutiny here than on
mechanically-parsed fields.

**Language bindings.** `bindings/rust/`, `bindings/python/`, and
`bindings/go/` are deliberately thin wrappers around the same embedded
catalog. They expose the same method names and pass the same golden-value
tests (MI300X, Strix Halo). If you change one binding's API shape, mirror the
change in the other two, or explain in the PR why it doesn't apply.

**Hardware validation scripts.** `tools/hardware_validation/` holds scripts
that run *on* real AMD hardware to produce evidence for a hand-validated
note, as opposed to `tools/catalog_build/`'s offline, document-parsing
pipeline. They're not part of CI (some need packages, like a ROCm build of
PyTorch, that this project's own dependencies deliberately don't include)
and never write to `notes.json` themselves — a human still reviews the
output and writes the note.

**Agent skill.** `skills/amd-platform-catalog/` follows the agentskills.io
specification. Its bundled snapshot (`assets/catalog.json`) is a real
committed copy, not a symlink, so run `scripts/sync_catalog_snapshot.sh`
after regenerating the canonical catalog.

**Docs.** Most of the Sphinx site under `docs/` pulls its content from
`README.md` and `PRD.md` via MyST `include` directives, so edit those two
files rather than the `docs/*.md` pages directly. See README.md's
"Documentation site" section for which page maps to which source section.

## Running the checks locally

```bash
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest tests/
(cd bindings/rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test)
(cd bindings/go && gofmt -l . && go vet ./... && go test ./...)
```

`.github/workflows/ci.yml` runs the same commands, plus `bindings/python`'s
own test suite. `security.yml` runs a secret scan and a
dependency-vulnerability review; `codeql.yml` runs CodeQL against the Python
and Go code.

## Opening a pull request

All changes go through a pull request; `main` is protected and requires CI,
security, and CodeQL to pass before merging. Keep a PR focused on one change,
and explain why, not just what, especially for a data correction or a new
source: a reviewer needs to know how you verified it.

## License

Not decided yet (see `PRD.md` §11); the project is currently leaning MIT.
