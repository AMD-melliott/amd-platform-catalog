"""Validates skills/amd-platform-catalog against the agentskills.io spec
(https://agentskills.io/specification) and checks it stays in sync with the
canonical catalog. `pyyaml` is a test-only dependency -- the skill's own
script stays stdlib-only per its `compatibility` frontmatter field.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

REPO_ROOT = Path(__file__).parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "amd-platform-catalog"
SKILL_MD = SKILL_DIR / "SKILL.md"
LOOKUP_SCRIPT = SKILL_DIR / "scripts" / "catalog_lookup.py"

SCHEMA = json.loads((REPO_ROOT / "catalog" / "schema" / "catalog.schema.json").read_text())

KNOWN_FRONTMATTER_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def _load_skill_md() -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(SKILL_MD.read_text())
    assert match, "SKILL.md must start with a --- delimited YAML frontmatter block"
    frontmatter_text, body = match.groups()
    frontmatter = yaml.safe_load(frontmatter_text)
    assert isinstance(frontmatter, dict), "frontmatter must parse as a mapping"
    return frontmatter, body


def test_skill_md_exists():
    assert SKILL_MD.is_file()


def test_directory_name_matches_frontmatter_name():
    # agentskills.io spec: "Must match the parent directory name."
    frontmatter, _ = _load_skill_md()
    assert frontmatter["name"] == SKILL_DIR.name


def test_name_field_follows_spec_pattern():
    frontmatter, _ = _load_skill_md()
    name = frontmatter["name"]
    assert 1 <= len(name) <= 64
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), (
        f"name {name!r} must be lowercase alphanumeric + single hyphens, no leading/trailing/consecutive hyphens"
    )


def test_description_field_present_and_within_length():
    frontmatter, _ = _load_skill_md()
    description = frontmatter["description"]
    assert isinstance(description, str)
    assert 1 <= len(description) <= 1024


def test_compatibility_field_within_length_if_present():
    frontmatter, _ = _load_skill_md()
    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        assert 1 <= len(compatibility) <= 500


def test_license_field_not_asserted():
    # PRD §11: the repo's license is still undecided -- SKILL.md must not
    # assert one it doesn't have.
    frontmatter, _ = _load_skill_md()
    assert "license" not in frontmatter


def test_metadata_is_a_string_to_string_map_if_present():
    frontmatter, _ = _load_skill_md()
    metadata = frontmatter.get("metadata")
    if metadata is not None:
        assert isinstance(metadata, dict)
        for key, value in metadata.items():
            assert isinstance(key, str)
            assert isinstance(value, str)


def test_only_known_frontmatter_fields_are_used():
    frontmatter, _ = _load_skill_md()
    unknown = set(frontmatter) - KNOWN_FRONTMATTER_FIELDS
    assert not unknown, f"unrecognized frontmatter field(s): {unknown}"


def test_skill_md_body_is_under_recommended_line_count():
    # agentskills.io: "Keep your main SKILL.md under 500 lines."
    _, body = _load_skill_md()
    assert len(body.splitlines()) <= 500


def test_body_references_only_files_that_exist():
    # agentskills.io: file references use paths relative to the skill root.
    _, body = _load_skill_md()
    referenced = set(re.findall(r"\b(?:scripts|assets|references)/[\w.\-/]+", body))
    assert referenced, "expected SKILL.md to reference at least one bundled file"
    for relative_path in referenced:
        assert (SKILL_DIR / relative_path).is_file(), f"SKILL.md references missing file: {relative_path}"


def test_lookup_script_is_executable_with_a_python_shebang():
    assert LOOKUP_SCRIPT.stat().st_mode & 0o111, "catalog_lookup.py should be executable"
    first_line = LOOKUP_SCRIPT.read_text().splitlines()[0]
    assert first_line.startswith("#!"), "catalog_lookup.py should start with a shebang"
    assert "python3" in first_line


def test_bundled_catalog_snapshot_is_valid_and_matches_schema():
    catalog = json.loads((SKILL_DIR / "assets" / "catalog.json").read_text())
    jsonschema.Draft202012Validator(SCHEMA).validate(catalog)


def test_bundled_catalog_snapshot_matches_canonical_catalog():
    # The skill bundles a real copy (not a symlink -- see SKILL.md/PRD §7.4)
    # so it survives an installer that fetches only this subdirectory. That
    # means it can silently drift from catalog/catalog.json if
    # sync_catalog_snapshot.sh isn't re-run; this test is the tripwire.
    bundled = (SKILL_DIR / "assets" / "catalog.json").read_text()
    canonical = (REPO_ROOT / "catalog" / "catalog.json").read_text()
    assert bundled == canonical, "run skills/amd-platform-catalog/scripts/sync_catalog_snapshot.sh to resync"


def _run_lookup(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(LOOKUP_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_lookup_resolve_mi300x_golden():
    result = _run_lookup("resolve", "74a1")
    assert result.returncode == 0
    entry = json.loads(result.stdout)
    assert entry["found"] is True
    assert entry["product_name"] == "MI300X"
    assert entry["generation"] == "CDNA3"
    assert entry["precision_support"]["fp8_e4m3_fnuz"] is True


def test_lookup_resolve_strix_halo_has_no_precision_support():
    result = _run_lookup("resolve", "1586")
    assert result.returncode == 0
    entry = json.loads(result.stdout)
    assert entry["product_name"] == "AMD Ryzen AI Max+ PRO 395"
    assert "precision_support" not in entry


def test_lookup_notes_surfaces_strix_halo_precision_note():
    result = _run_lookup("notes", "1586")
    assert result.returncode == 0
    notes = json.loads(result.stdout)["notes"]
    assert any(n["field"] == "precision_support" and "hand-validated" in n["note"] for n in notes)


def test_lookup_npu_has_three_ambiguous_hw_gens():
    result = _run_lookup("npu", "17f0")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["count"] == 3


def test_lookup_unknown_device_reports_plainly_instead_of_guessing():
    result = _run_lookup("gpu", "ffff")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload == {"found": False, "message": "not yet cataloged", "device_id": "ffff"}
