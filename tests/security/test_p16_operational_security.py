"""P16 authentication, browser boundary, and secret isolation tests."""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aegisquant.api.app import create_app
from aegisquant.readmodels.p15_bootstrap import build_p15_snapshot
from aegisquant.security.auth import AuthenticationError, OIDCBearerVerifier
from aegisquant.security.isolation import SecretClass, ServiceRole, validate_secret_mounts


def verifier_and_token(project_root: object) -> tuple[OIDCBearerVerifier, str]:
    del project_root
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    now = datetime.now(UTC)
    payload = {
        "iss": "https://identity.example.test",
        "aud": "aegisquant-dashboard",
        "sub": "operator-1",
        "scope": "dashboard:read",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(payload, private, algorithm="EdDSA")
    return (
        OIDCBearerVerifier(
            issuer="https://identity.example.test",
            audience="aegisquant-dashboard",
            public_key=public,
        ),
        token,
    )


def test_authenticated_api_enforces_bearer_scope_and_security_headers(project_root: Path) -> None:
    verifier, token = verifier_and_token(project_root)
    app = create_app(build_p15_snapshot(project_root), token_verifier=verifier)
    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        denied = client.get("/api/v1/overview")
        allowed = client.get(
            "/api/v1/overview",
            headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": "corr-auth-001"},
        )
        write = client.post("/api/v1/overview", headers={"Authorization": f"Bearer {token}"})
    assert health.status_code == 200
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"
    assert allowed.status_code == 200
    assert allowed.headers["x-correlation-id"] == "corr-auth-001"
    assert "default-src 'none'" in allowed.headers["content-security-policy"]
    assert allowed.headers["x-frame-options"] == "DENY"
    assert write.status_code == 405
    assert token not in denied.text + allowed.text + write.text


def test_token_verifier_rejects_missing_scope_and_algorithm_confusion() -> None:
    verifier, _ = verifier_and_token(None)
    with pytest.raises(AuthenticationError, match="authentication required"):
        verifier.authenticate(None)
    with pytest.raises(ValueError, match="asymmetric"):
        OIDCBearerVerifier(
            issuer="https://identity.example.test",
            audience="aegisquant-dashboard",
            public_key="public",
            algorithms=("HS256",),
        )


def test_research_and_all_services_are_denied_live_secrets() -> None:
    validate_secret_mounts(ServiceRole.RESEARCH, frozenset())
    with pytest.raises(PermissionError, match="not permitted"):
        validate_secret_mounts(ServiceRole.RESEARCH, frozenset({SecretClass.TESTNET_API}))
    for role in ServiceRole:
        with pytest.raises(PermissionError, match="LIVE-LOCKED"):
            validate_secret_mounts(role, frozenset({SecretClass.LIVE_API}))
