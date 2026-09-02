"""Validate catalog.json against catalog/schema/catalog.schema.json (PRD §6, §8)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema

DEFAULT_SCHEMA = Path(__file__).resolve().parents[2] / "catalog" / "schema" / "catalog.schema.json"
DEFAULT_CATALOG = Path("catalog/catalog.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path, nargs="?", default=DEFAULT_CATALOG)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args(argv)

    schema = json.loads(args.schema.read_text())
    catalog = json.loads(args.catalog.read_text())

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(catalog), key=lambda e: list(e.path))
    if errors:
        for error in errors:
            location = "/".join(str(part) for part in error.path) or "<root>"
            print(f"{location}: {error.message}", file=sys.stderr)
        print(f"{args.catalog}: FAILED schema validation ({len(errors)} error(s))", file=sys.stderr)
        return 1

    print(f"{args.catalog}: valid against {args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
