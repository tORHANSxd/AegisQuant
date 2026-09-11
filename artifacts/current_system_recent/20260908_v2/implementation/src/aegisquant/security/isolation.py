"""Secret-mount policy separating research, read, and execution roles."""

from __future__ import annotations

from enum import StrEnum


class ServiceRole(StrEnum):
    RESEARCH = "research"
    READ_API = "read_api"
    TESTNET_EXECUTION = "testnet_execution"


class SecretClass(StrEnum):
    OIDC_PUBLIC_KEY = "oidc_public_key"
    READ_DATABASE = "read_database"
    TESTNET_API = "testnet_api"
    LIVE_API = "live_api"


ALLOWED_SECRET_MOUNTS: dict[ServiceRole, frozenset[SecretClass]] = {
    ServiceRole.RESEARCH: frozenset(),
    ServiceRole.READ_API: frozenset({SecretClass.OIDC_PUBLIC_KEY, SecretClass.READ_DATABASE}),
    ServiceRole.TESTNET_EXECUTION: frozenset({SecretClass.TESTNET_API}),
}


def validate_secret_mounts(role: ServiceRole, mounts: frozenset[SecretClass]) -> None:
    """Reject every Live secret and every role expansion not explicitly allowed."""
    if SecretClass.LIVE_API in mounts:
        raise PermissionError("AQ-SECURITY-LIVE-LOCKED: live secret mounts are unavailable")
    denied = mounts - ALLOWED_SECRET_MOUNTS[role]
    if denied:
        rendered = ", ".join(sorted(item.value for item in denied))
        raise PermissionError(f"secret mounts are not permitted for {role.value}: {rendered}")
