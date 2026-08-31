"""Strict configuration schema and canonical hash contracts."""

# pyright: reportUnknownMemberType=false

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from aegisquant.config.models import (
    AppConfig,
    DatabaseConfig,
    RuntimeConfig,
    RuntimeEnvironment,
)


def app_config() -> AppConfig:
    return AppConfig(
        runtime=RuntimeConfig(environment=RuntimeEnvironment.RESEARCH),
        database=DatabaseConfig(dsn_secret_key="AEGISQUANT_POSTGRES_DSN"),
    )


def test_unknown_fields_and_secret_values_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AppConfig.model_validate_json(
            '{"runtime":{"environment":"RESEARCH"},'
            '"database":{"dsn_secret_key":"AEGISQUANT_POSTGRES_DSN"},"unknown":true}'  # pragma: allowlist secret
        )
    with pytest.raises(ValidationError, match="secret key name"):
        DatabaseConfig(
            dsn_secret_key="postgresql://user@host/database"  # pragma: allowlist secret
        )


def test_live_environment_and_capabilities_remain_locked() -> None:
    with pytest.raises(ValidationError, match="LIVE-LOCKED"):
        RuntimeConfig(environment=RuntimeEnvironment.LIVE)
    with pytest.raises(ValidationError, match="LIVE-LOCKED"):
        RuntimeConfig(environment=RuntimeEnvironment.PAPER, live_trading=True)


def test_content_hash_is_deterministic_and_schema_validates_dump() -> None:
    config = app_config()
    assert config.content_hash() == app_config().content_hash()
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "schemas/config/app-config-v1.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(config.model_dump(mode="json"))
