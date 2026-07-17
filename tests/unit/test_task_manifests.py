"""Offline structural validation of the task manifests (spec 13.3, 13.4).

The harness core is stdlib-only, so manifests are validated with a minimal
hand-rolled structural check instead of the jsonschema package. The vocabulary
constants below are cross-checked against datasets/manifests/task-manifest.schema.json
so the two cannot drift apart.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

MANIFEST_DIR = Path(__file__).resolve().parents[2] / "datasets" / "manifests"
SCHEMA_PATH = MANIFEST_DIR / "task-manifest.schema.json"

REQUIRED_KEYS = {
    "id",
    "title",
    "category",
    "partition",
    "modules",
    "repository",
    "starting_revision",
    "description",
    "acceptance_criteria",
    "constraints",
    "non_goals",
    "allowed_capabilities",
    "prohibited_capabilities",
    "risk_classification",
    "visible_validation",
    "hidden_validation",
    "baseline_configuration",
    "time_budget",
    "cost_budget",
    "expected_artifacts",
    "human_review_rubric",
    "known_ambiguities",
}

OPTIONAL_KEYS = {
    "recommended_context_sources",
    "expected_failure_modes",
    "parallelization_opportunities",
    "security_notes",
    "instructor_notes",
}

CAPABILITY_CLASSES = {
    "class-0-observation",
    "class-1-local-reversible",
    "class-2-local-consequential",
    "class-3-external-reversible",
    "class-4-external-consequential",
    "class-5-prohibited",
}

CATEGORIES = {
    "repository-investigation",
    "small-feature-implementation",
    "targeted-bug-fixing",
    "failing-test-diagnosis",
    "test-creation",
    "code-review",
    "review-finding-verification",
    "targeted-refactoring",
    "documentation-correction",
    "issue-triage",
    "integration-conflict-resolution",
    "release-preparation",
}

PARTITIONS = {"practice", "development", "held-out"}
BASELINES = {"A", "B", "C", "D", "E", "F"}
TIME_CLASSES = {"time-class-short", "time-class-medium", "time-class-long"}
COST_CLASSES = {"cost-class-replay", "cost-class-small", "cost-class-medium", "cost-class-large"}
METRIC_CATEGORIES = {"outcome", "process", "safety", "economic", "human-impact"}
CHECK_KINDS = {"command", "artifact", "human-review"}

ID_PATTERN = re.compile(r"^[a-z]+-[0-9]{3}$")
MODULE_PATTERN = re.compile(r"^(M(10|[0-9])|evidence-gates|capstone)$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GRADER_PATTERN = re.compile(r"^grader:[a-z]+-[0-9]{3}$")


def _manifest_paths() -> list[Path]:
    return sorted(MANIFEST_DIR.glob("bk-*.json"))


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict), f"{path.name}: manifest must be a JSON object"
    return data


def _assert_string_list(manifest: dict[str, Any], key: str, *, non_empty: bool) -> None:
    value = manifest[key]
    assert isinstance(value, list), f"{key} must be a list"
    if non_empty:
        assert value, f"{key} must not be empty"
    for item in value:
        assert isinstance(item, str) and item, f"{key} items must be non-empty strings"


def test_seed_dataset_is_complete() -> None:
    names = {path.stem for path in _manifest_paths()}
    assert names == {f"bk-{n:03d}" for n in range(1, 13)}


def test_ids_are_unique() -> None:
    ids = [_load(path)["id"] for path in _manifest_paths()]
    assert len(ids) == len(set(ids))


def test_seed_partitions_match_spec_section_13_4() -> None:
    partitions = {path.stem: _load(path)["partition"] for path in _manifest_paths()}
    assert {tid for tid, p in partitions.items() if p == "practice"} == {
        "bk-001",
        "bk-002",
        "bk-007",
    }
    assert {tid for tid, p in partitions.items() if p == "held-out"} == {"bk-011", "bk-012"}
    assert all(p in PARTITIONS for p in partitions.values())


@pytest.mark.parametrize("path", _manifest_paths(), ids=lambda p: p.stem)
def test_manifest_is_structurally_valid(path: Path) -> None:
    manifest = _load(path)

    keys = set(manifest)
    assert keys >= REQUIRED_KEYS, f"missing required keys: {sorted(REQUIRED_KEYS - keys)}"
    unknown = keys - REQUIRED_KEYS - OPTIONAL_KEYS
    assert not unknown, f"unknown keys: {sorted(unknown)}"

    assert manifest["id"] == path.stem, "id must agree with the filename"
    assert ID_PATTERN.match(manifest["id"])

    for key in ("title", "description"):
        assert isinstance(manifest[key], str) and manifest[key]

    assert REPOSITORY_PATTERN.match(manifest["repository"])
    assert REVISION_PATTERN.match(manifest["starting_revision"])

    assert manifest["category"] in CATEGORIES
    assert manifest["partition"] in PARTITIONS
    assert manifest["baseline_configuration"] in BASELINES
    assert manifest["time_budget"] in TIME_CLASSES
    assert manifest["cost_budget"] in COST_CLASSES
    assert manifest["risk_classification"] in CAPABILITY_CLASSES

    _assert_string_list(manifest, "modules", non_empty=True)
    for module in manifest["modules"]:
        assert MODULE_PATTERN.match(module), f"bad module tag {module!r}"

    _assert_string_list(manifest, "acceptance_criteria", non_empty=True)
    _assert_string_list(manifest, "constraints", non_empty=False)
    _assert_string_list(manifest, "non_goals", non_empty=False)
    _assert_string_list(manifest, "expected_artifacts", non_empty=True)
    _assert_string_list(manifest, "known_ambiguities", non_empty=False)
    for key in (
        "recommended_context_sources",
        "expected_failure_modes",
        "parallelization_opportunities",
    ):
        if key in manifest:
            _assert_string_list(manifest, key, non_empty=False)
    for key in ("security_notes", "instructor_notes"):
        if key in manifest:
            assert isinstance(manifest[key], str) and manifest[key]

    allowed = manifest["allowed_capabilities"]
    prohibited = manifest["prohibited_capabilities"]
    for name, value in (("allowed_capabilities", allowed), ("prohibited_capabilities", prohibited)):
        assert isinstance(value, list) and value, f"{name} must be a non-empty list"
        assert set(value) <= CAPABILITY_CLASSES, f"{name} contains unknown classes"
        assert len(value) == len(set(value)), f"{name} has duplicates"
    assert not set(allowed) & set(prohibited), "a class cannot be both allowed and prohibited"
    assert "class-5-prohibited" in prohibited
    assert manifest["risk_classification"] in allowed

    checks = manifest["visible_validation"]
    assert isinstance(checks, list) and checks
    for check in checks:
        assert isinstance(check, dict)
        assert set(check) <= {"kind", "command", "description"}
        assert check.get("kind") in CHECK_KINDS
        assert isinstance(check.get("description"), str) and check["description"]
        if check["kind"] == "command":
            assert isinstance(check.get("command"), str) and check["command"]
        else:
            assert "command" not in check

    assert isinstance(manifest["hidden_validation"], str)
    assert GRADER_PATTERN.match(manifest["hidden_validation"])
    assert manifest["hidden_validation"] == f"grader:{manifest['id']}"

    rubric = manifest["human_review_rubric"]
    assert isinstance(rubric, list) and rubric
    for item in rubric:
        assert isinstance(item, dict)
        assert set(item) == {"criterion", "metric_category"}
        assert isinstance(item["criterion"], str) and item["criterion"]
        assert item["metric_category"] in METRIC_CATEGORIES


def test_vocabularies_agree_with_json_schema() -> None:
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        schema = json.load(fh)

    assert set(schema["required"]) == REQUIRED_KEYS
    assert set(schema["properties"]) == REQUIRED_KEYS | OPTIONAL_KEYS
    assert set(schema["$defs"]["capabilityClass"]["enum"]) == CAPABILITY_CLASSES
    assert set(schema["properties"]["category"]["enum"]) == CATEGORIES
    assert set(schema["properties"]["partition"]["enum"]) == PARTITIONS
    assert set(schema["properties"]["baseline_configuration"]["enum"]) == BASELINES
    assert set(schema["properties"]["time_budget"]["enum"]) == TIME_CLASSES
    assert set(schema["properties"]["cost_budget"]["enum"]) == COST_CLASSES
    rubric_enum = schema["$defs"]["rubricItem"]["properties"]["metric_category"]["enum"]
    assert set(rubric_enum) == METRIC_CATEGORIES
    kinds = schema["$defs"]["validationCheck"]["properties"]["kind"]["enum"]
    assert set(kinds) == CHECK_KINDS
