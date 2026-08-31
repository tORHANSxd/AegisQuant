"""Validated configuration models with deterministic content hashes."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

SECRET_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class RuntimeEnvironment(StrEnum):
    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    TESTNET = "TESTNET"
    CANARY = "CANARY"
    LIVE = "LIVE"


class RuntimeConfig(StrictConfigModel):
    environment: RuntimeEnvironment
    display_timezone: str = "UTC"
    live_trading: bool = False
    order_submission_enabled: bool = False
    secret_loading_enabled: bool = False

    @model_validator(mode="after")
    def enforce_p01_lock(self) -> RuntimeConfig:
        if self.environment is RuntimeEnvironment.LIVE:
            raise ValueError("AQ-SECURITY-LIVE-LOCKED: Live environment is unavailable in P01")
        if self.live_trading or self.order_submission_enabled or self.secret_loading_enabled:
            raise ValueError("AQ-SECURITY-LIVE-LOCKED: runtime capability is locked")
        return self


class DatabaseConfig(StrictConfigModel):
    dsn_secret_key: str
    pool_size: int = 5
    statement_timeout_ms: int = 30_000

    @model_validator(mode="after")
    def only_secret_reference_is_allowed(self) -> DatabaseConfig:
        if SECRET_KEY_RE.fullmatch(self.dsn_secret_key) is None:
            raise ValueError("database config accepts a secret key name, never a DSN value")
        if self.pool_size < 1 or self.statement_timeout_ms < 1:
            raise ValueError("database limits must be positive")
        return self


class AppConfig(StrictConfigModel):
    schema_version: str = "1.0.0"
    runtime: RuntimeConfig
    database: DatabaseConfig

    def content_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(payload).hexdigest()
