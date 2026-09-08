"""Official source identity rules and detached-signature verification."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import ArtifactId, SourceId, SourceIdentityId
from aegisquant.domain.time import assert_point_in_time, ensure_utc
from aegisquant.truth.contracts import (
    DetachedSignatureState,
    DetachedSignatureVerification,
    IdentityFactor,
    OfficialIdentityAssessment,
    OfficialIdentityObservation,
    OfficialIdentityState,
    PublicKeyAlgorithm,
)
from aegisquant.truth.source_registry import SourceRegistry


def _canonical_host(url: str) -> tuple[str, bool]:
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise ValueError("AQ-TRUTH-OFFICIAL-IDENTITY-URL-HAS-NO-HOST")
    unicode_present = any(ord(character) > 127 for character in host)
    try:
        canonical = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("AQ-TRUTH-OFFICIAL-IDENTITY-INVALID-IDNA-HOST") from error
    return canonical, unicode_present


def _canonical_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    host, _ = _canonical_host(url)
    port = f":{parsed.port}" if parsed.port is not None else ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), f"{host}{port}", path, "", ""))


def _host_matches(host: str, official_domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in official_domains)


def _signature_result(
    *,
    source_id: SourceId,
    source_identity_id: SourceIdentityId,
    key_id: str,
    key_fingerprint_sha256: str | None,
    payload_sha256: str,
    signature_sha256: str,
    state: DetachedSignatureState,
    reason_code: str,
    observed_at: datetime,
    available_at: datetime,
) -> DetachedSignatureVerification:
    identity = {
        "source_id": str(source_id),
        "source_identity_id": str(source_identity_id),
        "key_id": key_id,
        "key_fingerprint_sha256": key_fingerprint_sha256,
        "payload_sha256": payload_sha256,
        "signature_sha256": signature_sha256,
        "state": state.value,
        "reason_code": reason_code,
        "observed_at": observed_at.isoformat(),
        "available_at": available_at.isoformat(),
    }
    return DetachedSignatureVerification(
        verification_id=ArtifactId(canonical_sha256(identity)),
        source_id=source_id,
        source_identity_id=source_identity_id,
        key_id=key_id,
        key_fingerprint_sha256=key_fingerprint_sha256,
        payload_sha256=payload_sha256,
        signature_sha256=signature_sha256,
        state=state,
        reason_codes=(reason_code,),
        observed_at=observed_at,
        available_at=available_at,
    )


def verify_detached_signature(
    *,
    registry: SourceRegistry,
    source_id: SourceId,
    source_identity_id: SourceIdentityId,
    key_id: str,
    payload: bytes,
    signature: bytes,
    observed_at: datetime,
    available_at: datetime,
    decision_time: datetime,
) -> DetachedSignatureVerification:
    """Verify one payload against a registry key visible at decision time."""

    observed = ensure_utc(observed_at)
    available = ensure_utc(available_at)
    decision = ensure_utc(decision_time)
    if observed > available:
        raise ValueError("AQ-TRUTH-DETACHED-SIGNATURE-TIME-ORDER")
    assert_point_in_time(available_time=available, decision_time=decision)
    entry = registry.entry_as_of(source_id, decision_time=decision)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    signature_sha256 = hashlib.sha256(signature).hexdigest()
    matching = tuple(key for key in entry.public_keys if key.key_id == key_id)
    if not matching:
        return _signature_result(
            source_id=source_id,
            source_identity_id=source_identity_id,
            key_id=key_id,
            key_fingerprint_sha256=None,
            payload_sha256=payload_sha256,
            signature_sha256=signature_sha256,
            state=DetachedSignatureState.KEY_NOT_FOUND,
            reason_code="AQ-TRUTH-DETACHED-SIGNATURE-KEY-NOT-FOUND",
            observed_at=observed,
            available_at=available,
        )
    key_record = matching[0]
    active = (
        key_record.available_at <= decision
        and key_record.valid_from <= observed
        and (key_record.valid_to is None or observed < key_record.valid_to)
        and (key_record.revoked_at is None or observed < key_record.revoked_at)
    )
    if not active:
        return _signature_result(
            source_id=source_id,
            source_identity_id=source_identity_id,
            key_id=key_id,
            key_fingerprint_sha256=key_record.fingerprint_sha256,
            payload_sha256=payload_sha256,
            signature_sha256=signature_sha256,
            state=DetachedSignatureState.KEY_NOT_ACTIVE,
            reason_code="AQ-TRUTH-DETACHED-SIGNATURE-KEY-NOT-ACTIVE",
            observed_at=observed,
            available_at=available,
        )
    if key_record.algorithm is not PublicKeyAlgorithm.ED25519:
        return _signature_result(
            source_id=source_id,
            source_identity_id=source_identity_id,
            key_id=key_id,
            key_fingerprint_sha256=key_record.fingerprint_sha256,
            payload_sha256=payload_sha256,
            signature_sha256=signature_sha256,
            state=DetachedSignatureState.UNSUPPORTED_ALGORITHM,
            reason_code="AQ-TRUTH-DETACHED-SIGNATURE-UNSUPPORTED-ALGORITHM",
            observed_at=observed,
            available_at=available,
        )
    try:
        public_key = serialization.load_pem_public_key(key_record.public_key_pem.encode("ascii"))
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("registry key type does not match ED25519")
        public_key.verify(signature, payload)
    except InvalidSignature:
        state = DetachedSignatureState.INVALID
        reason = "AQ-TRUTH-DETACHED-SIGNATURE-INVALID"
    except (TypeError, ValueError):
        state = DetachedSignatureState.ERROR
        reason = "AQ-TRUTH-DETACHED-SIGNATURE-KEY-DECODE-ERROR"
    else:
        state = DetachedSignatureState.VALID
        reason = "AQ-TRUTH-DETACHED-SIGNATURE-VALID"
    return _signature_result(
        source_id=source_id,
        source_identity_id=source_identity_id,
        key_id=key_id,
        key_fingerprint_sha256=key_record.fingerprint_sha256,
        payload_sha256=payload_sha256,
        signature_sha256=signature_sha256,
        state=state,
        reason_code=reason,
        observed_at=observed,
        available_at=available,
    )


def assess_official_identity(
    *,
    registry: SourceRegistry,
    observation: OfficialIdentityObservation,
    decision_time: datetime,
    signature_verifications: Iterable[DetachedSignatureVerification] = (),
) -> OfficialIdentityAssessment:
    """Apply registry rules; a matching domain by itself can never authenticate."""

    decision = ensure_utc(decision_time)
    assert_point_in_time(available_time=observation.available_at, decision_time=decision)
    entry = registry.entry_as_of(observation.source_id, decision_time=decision)
    matched: set[IdentityFactor] = set()
    mismatched: set[IdentityFactor] = set()
    reasons: set[str] = {"AQ-TRUTH-SOURCE-TIER-IS-PRIOR-ONLY"}

    if observation.observed_url is not None:
        host, unicode_present = _canonical_host(observation.observed_url)
        if _host_matches(host, entry.official_domains):
            matched.add(IdentityFactor.DOMAIN)
        else:
            mismatched.add(IdentityFactor.DOMAIN)
            reasons.add("AQ-TRUTH-OFFICIAL-DOMAIN-MISMATCH")
            if unicode_present:
                reasons.add("AQ-TRUTH-OFFICIAL-DOMAIN-UNICODE-HOMOGRAPH")

    if observation.social_account_id is not None:
        social_match = any(
            account.platform.casefold() == observation.social_platform.casefold()
            and account.account_id == observation.social_account_id
            for account in entry.official_social_accounts
            if observation.social_platform is not None
        )
        (matched if social_match else mismatched).add(IdentityFactor.SOCIAL_ACCOUNT)
        if not social_match:
            reasons.add("AQ-TRUTH-OFFICIAL-SOCIAL-ACCOUNT-MISMATCH")

    if observation.api_endpoint is not None:
        canonical_endpoint = _canonical_endpoint(observation.api_endpoint)
        endpoint_match = canonical_endpoint in {
            _canonical_endpoint(endpoint) for endpoint in entry.known_api_endpoints
        }
        (matched if endpoint_match else mismatched).add(IdentityFactor.API_ENDPOINT)
        if not endpoint_match:
            reasons.add("AQ-TRUTH-OFFICIAL-API-ENDPOINT-MISMATCH")

    if observation.detached_signature_verification_id is not None:
        visible = {
            verification.verification_id: verification
            for verification in signature_verifications
            if verification.available_at <= decision
        }
        verification = visible.get(observation.detached_signature_verification_id)
        signature_match = (
            verification is not None
            and verification.source_id == observation.source_id
            and verification.source_identity_id == observation.source_identity_id
            and verification.state is DetachedSignatureState.VALID
            and any(
                key.fingerprint_sha256 == verification.key_fingerprint_sha256
                for key in entry.public_keys
            )
        )
        (matched if signature_match else mismatched).add(IdentityFactor.DETACHED_SIGNATURE)
        if not signature_match:
            reasons.add("AQ-TRUTH-OFFICIAL-DETACHED-SIGNATURE-MISMATCH")

    if mismatched:
        state = OfficialIdentityState.REJECTED
        reasons.add("AQ-TRUTH-OFFICIAL-IDENTITY-REJECTED")
    elif (
        IdentityFactor.DETACHED_SIGNATURE in matched
        or IdentityFactor.SOCIAL_ACCOUNT in matched
        or {IdentityFactor.DOMAIN, IdentityFactor.API_ENDPOINT} <= matched
    ):
        state = OfficialIdentityState.AUTHENTIC
        reasons.add("AQ-TRUTH-OFFICIAL-IDENTITY-AUTHENTIC")
    else:
        state = OfficialIdentityState.INSUFFICIENT_EVIDENCE
        reasons.add("AQ-TRUTH-OFFICIAL-IDENTITY-INSUFFICIENT-INDEPENDENT-FACTORS")

    matched_tuple = tuple(sorted(matched, key=lambda item: item.value))
    mismatched_tuple = tuple(sorted(mismatched, key=lambda item: item.value))
    reason_tuple = tuple(sorted(reasons))
    payload = {
        "source_id": str(observation.source_id),
        "source_identity_id": str(observation.source_identity_id),
        "registry_entry_id": str(entry.registry_entry_id),
        "state": state.value,
        "matched_factors": [item.value for item in matched_tuple],
        "mismatched_factors": [item.value for item in mismatched_tuple],
        "reason_codes": list(reason_tuple),
        "observed_at": observation.observed_at.isoformat(),
        "available_at": observation.available_at.isoformat(),
    }
    return OfficialIdentityAssessment(
        assessment_id=ArtifactId(canonical_sha256(payload)),
        source_id=observation.source_id,
        source_identity_id=observation.source_identity_id,
        registry_entry_id=entry.registry_entry_id,
        state=state,
        matched_factors=matched_tuple,
        mismatched_factors=mismatched_tuple,
        reason_codes=reason_tuple,
        observed_at=observation.observed_at,
        available_at=observation.available_at,
    )
