"""Machine-executable source policy contract tests."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


def validator() -> tuple[Draft202012Validator, dict[str, object]]:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "schemas/source_processing_policy.schema.json").read_text(encoding="utf-8")
    )
    policy = json.loads(
        (root / "configs/data_sources/default_deny_policy.json").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER), policy


def test_default_deny_policy_is_valid_and_denies_every_boundary() -> None:
    policy_validator, policy = validator()

    policy_validator.validate(policy)
    assert policy["policy_status"] == "DENIED"
    assert policy["access_method"] == "NONE"
    assert policy["raw_storage"] == "PROHIBITED"
    assert policy["derived_storage"] == "PROHIBITED"
    assert policy["cloud_inference"] == "PROHIBITED"
    assert policy["display_mode"] == "NONE"
    assert policy["retention_days"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_method", "OFFICIAL_API"),
        ("raw_storage", "ENCRYPTED_LOCAL"),
        ("derived_storage", "ALLOWED"),
        ("cloud_inference", "ALLOWED"),
        ("fine_tuning", "EXPLICIT_APPROVAL_REQUIRED"),
        ("display_mode", "DERIVED_ONLY"),
        ("redistribution", "IDS_ONLY"),
        ("retention_days", 1),
    ],
)
def test_denied_policy_cannot_enable_processing(field: str, value: object) -> None:
    policy_validator, policy = validator()
    policy[field] = value

    assert list(policy_validator.iter_errors(policy))
