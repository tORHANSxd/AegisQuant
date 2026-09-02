"""Offline bearer-token verification for the private read dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast

import jwt

READ_SCOPE: Final = "dashboard:read"
ALGORITHMS: Final = ("EdDSA", "RS256")


class AuthenticationError(ValueError):
    """A deliberately generic authentication failure."""


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    scopes: frozenset[str]


class OIDCBearerVerifier:
    """Validate a signed OIDC-shaped JWT using an injected public key only."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        public_key: str | bytes,
        algorithms: tuple[str, ...] = ALGORITHMS,
        leeway_seconds: int = 30,
    ) -> None:
        if not issuer.startswith("https://"):
            raise ValueError("OIDC issuer must use HTTPS")
        if not audience or leeway_seconds < 0 or leeway_seconds > 300:
            raise ValueError("invalid OIDC audience or leeway")
        if not algorithms or set(algorithms) - set(ALGORITHMS):
            raise ValueError("only asymmetric EdDSA or RS256 tokens are accepted")
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._public_key = public_key
        self._algorithms = algorithms
        self._leeway = leeway_seconds

    def authenticate(self, authorization: str | None) -> Principal:
        if authorization is None or len(authorization) > 8192:
            raise AuthenticationError("authentication required")
        scheme, separator, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or separator != " " or not token or " " in token:
            raise AuthenticationError("authentication required")
        try:
            decoded = jwt.decode(
                token,
                key=self._public_key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise AuthenticationError("authentication required") from error
        payload = cast("dict[str, object]", decoded)
        subject = payload.get("sub")
        scope_value = payload.get("scope", "")
        if not isinstance(subject, str) or not subject or len(subject) > 128:
            raise AuthenticationError("authentication required")
        if not isinstance(scope_value, str):
            raise AuthenticationError("authentication required")
        scopes = frozenset(scope_value.split())
        if READ_SCOPE not in scopes:
            raise AuthenticationError("authentication required")
        return Principal(subject=subject, scopes=scopes)

    @staticmethod
    def utc_now() -> datetime:
        """Expose an aware clock for token-producing contract tests."""
        return datetime.now(UTC)
