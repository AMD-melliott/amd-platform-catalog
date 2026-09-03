## What changed and why

Describe the change and the reason for it. Link an issue if there is one.

## Area touched

- [ ] Ingestion pipeline (`tools/catalog_build/`) or `catalog/catalog.json`
- [ ] Notes overlay (`catalog/notes.json`)
- [ ] Rust binding (`bindings/rust/`)
- [ ] Python binding (`bindings/python/`)
- [ ] Go binding (`bindings/go/`)
- [ ] Agent skill (`skills/amd-platform-catalog/`)
- [ ] Docs (`docs/`, `README.md`, `PRD.md`)
- [ ] CI / tooling

## Testing

What did you run locally? For example:

```bash
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest tests/
(cd bindings/rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test)
(cd bindings/go && gofmt -l . && go vet ./... && go test ./...)
```

If you touched a binding's copy of `catalog.json`, say whether you re-ran the sync step (`go generate ./...` for Go, `scripts/sync_catalog_snapshot.sh` for the agent skill).

## Notes for the reviewer

Anything that needs a closer look: a notes-overlay change, a new source, a schema change, or an open question you're not sure about.
