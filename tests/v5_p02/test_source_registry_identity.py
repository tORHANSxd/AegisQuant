"""V5-P02 versioned source registry and official-identity rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.domain.errors import DomainError
from aegisquant.domain.identifiers import ArtifactId, SourceId, SourceIdentityId
from aegisquant.truth.contracts import (
    DetachedSignatureState,
    IdentityFactor,
    OfficialIdentityObservation,
    OfficialIdentityState,
    OfficialPublicKey,
    PublicKeyAlgorithm,
    SourceRegistryDocument,
    SourceRegistryEntry,
    SourceTier,
    SourceType,
)
from aegisquant.truth.identity import assess_official_identity, verify_detached_signature
from aegisquant.truth.source_registry import SourceRegistry, public_key_fingerprint_sha256

NOW = datetime(2026, 9, 2, 16, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
SOURCE_ID = SourceId("us-sec")
SOURCE_IDENTITY_ID = SourceIdentityId("source-identity:us-sec")


def _entry(*, public_keys: tuple[OfficialPublicKey, ...] = ()) -> SourceRegistryEntry:
    return SourceRegistryEntry(
        registry_entry_id=ArtifactId("source-registry:us-sec:v1"),
        source_id=SOURCE_ID,
        version=1,
        canonical_name="U.S. Securities and Exchange Commission",
        source_type=SourceType.REGULATOR,
        source_tier=SourceTier.S,
        official_domains=("sec.gov",),
        public_keys=public_keys,
        known_api_endpoints=("https://www.sec.gov/news/pressreleases.rss",),
        jurisdiction="US",
        topic_domains=("securities",),
        license_policy="public official source",
        evidence_references=("https://www.sec.gov/newsroom/press-releases",),
        valid_from=NOW - timedelta(days=1),
        available_at=NOW,
    )


def _registry(*, public_keys: tuple[OfficialPublicKey, ...] = ()) -> SourceRegistry:
    return SourceRegistry.from_document(
        SourceRegistryDocument(
            schema_version="1.0.0",
            registry_version=1,
            published_at=NOW,
            available_at=LATER,
            entries=(_entry(public_keys=public_keys),),
        )
    )


def _observation(**changes: object) -> OfficialIdentityObservation:
    payload: dict[str, object] = {
        "source_id": SOURCE_ID,
        "source_identity_id": SOURCE_IDENTITY_ID,
        "observed_url": "https://www.sec.gov/news/pressreleases.rss",
        "api_endpoint": "https://www.sec.gov/news/pressreleases.rss",
        "observed_at": NOW,
        "available_at": NOW,
    }
    payload.update(changes)
    return OfficialIdentityObservation.model_validate(payload)


def test_checked_in_registry_is_versioned_and_hash_order_invariant(project_root: Path) -> None:
    registry = SourceRegistry.from_yaml(project_root / "data/catalogs/v5_source_registry.yaml")
    assert len(registry.document.entries) == 4
    assert registry.entry_as_of(SOURCE_ID, decision_time=NOW).source_tier is SourceTier.S

    reverse = registry.document.model_copy(update={"entries": registry.document.entries[::-1]})
    assert reverse.content_sha256() == registry.content_hash()

    v1 = _entry()
    v2 = v1.model_copy(
        update={
            "registry_entry_id": ArtifactId("source-registry:us-sec:v2"),
            "version": 2,
            "supersedes_registry_entry_id": v1.registry_entry_id,
            "canonical_name": "SEC",
            "available_at": LATER,
        }
    )
    versioned = SourceRegistry.from_document(
        SourceRegistryDocument(
            schema_version="1.0.0",
            registry_version=2,
            published_at=NOW,
            available_at=LATER,
            entries=(v2, v1),
        )
    )
    assert versioned.entry_as_of(SOURCE_ID, decision_time=NOW).version == 1
    assert versioned.entry_as_of(SOURCE_ID, decision_time=LATER).version == 2
    with pytest.raises(DomainError, match="AQ-TRUTH-SOURCE-NOT-REGISTERED-AS-OF"):
        versioned.entry_as_of(SourceId("unknown-source"), decision_time=LATER)


def test_spoof_homograph_and_domain_only_evidence_fail_closed() -> None:
    registry = _registry()
    authentic = assess_official_identity(
        registry=registry,
        observation=_observation(),
        decision_time=NOW,
    )
    assert authentic.state is OfficialIdentityState.AUTHENTIC
    assert set(authentic.matched_factors) == {
        IdentityFactor.DOMAIN,
        IdentityFactor.API_ENDPOINT,
    }

    spoofed = assess_official_identity(
        registry=registry,
        observation=_observation(observed_url="https://www.sec.gov.attacker.example/news"),
        decision_time=NOW,
    )
    assert spoofed.state is OfficialIdentityState.REJECTED
    assert IdentityFactor.DOMAIN in spoofed.mismatched_factors

    homograph = assess_official_identity(
        registry=registry,
        observation=_observation(
            # The middle character in the host below is Unicode U+0435.
            observed_url="https://www.sеc.gov/news/pressreleases.rss",
        ),
        decision_time=NOW,
    )
    assert homograph.state is OfficialIdentityState.REJECTED
    assert "AQ-TRUTH-OFFICIAL-DOMAIN-UNICODE-HOMOGRAPH" in homograph.reason_codes

    domain_only = assess_official_identity(
        registry=registry,
        observation=_observation(api_endpoint=None),
        decision_time=NOW,
    )
    assert domain_only.state is OfficialIdentityState.INSUFFICIENT_EVIDENCE
    assert domain_only.tier_is_prior_only is True


def test_detached_signature_binds_source_identity_and_detects_tampering() -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    key = OfficialPublicKey(
        key_id="sec-test-key",
        algorithm=PublicKeyAlgorithm.ED25519,
        public_key_pem=public_key_pem,
        fingerprint_sha256=public_key_fingerprint_sha256(public_key_pem),
        valid_from=NOW - timedelta(days=1),
        available_at=NOW,
    )
    registry = _registry(public_keys=(key,))
    payload = b"official release payload"
    signature = private_key.sign(payload)
    valid = verify_detached_signature(
        registry=registry,
        source_id=SOURCE_ID,
        source_identity_id=SOURCE_IDENTITY_ID,
        key_id=key.key_id,
        payload=payload,
        signature=signature,
        observed_at=NOW,
        available_at=NOW,
        decision_time=NOW,
    )
    assert valid.state is DetachedSignatureState.VALID
    signed_observation = _observation(
        observed_url=None,
        api_endpoint=None,
        detached_signature_verification_id=valid.verification_id,
    )
    assessment = assess_official_identity(
        registry=registry,
        observation=signed_observation,
        decision_time=NOW,
        signature_verifications=(valid,),
    )
    assert assessment.state is OfficialIdentityState.AUTHENTIC
    assert assessment.matched_factors == (IdentityFactor.DETACHED_SIGNATURE,)

    invalid = verify_detached_signature(
        registry=registry,
        source_id=SOURCE_ID,
        source_identity_id=SOURCE_IDENTITY_ID,
        key_id=key.key_id,
        payload=payload + b" tampered",
        signature=signature,
        observed_at=NOW,
        available_at=NOW,
        decision_time=NOW,
    )
    assert invalid.state is DetachedSignatureState.INVALID
    rejected = assess_official_identity(
        registry=registry,
        observation=_observation(
            observed_url=None,
            api_endpoint=None,
            detached_signature_verification_id=invalid.verification_id,
        ),
        decision_time=NOW,
        signature_verifications=(invalid,),
    )
    assert rejected.state is OfficialIdentityState.REJECTED


@pytest.mark.parametrize(
    ("key_id", "valid_to", "revoked_at", "available_at"),
    (
        ("expired-key", NOW, None, NOW),
        ("revoked-key", None, NOW, NOW),
        ("future-key", None, None, LATER),
    ),
)
def test_inactive_or_unknown_registry_keys_fail_closed(
    key_id: str,
    valid_to: datetime | None,
    revoked_at: datetime | None,
    available_at: datetime,
) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    key = OfficialPublicKey(
        key_id=key_id,
        algorithm=PublicKeyAlgorithm.ED25519,
        public_key_pem=public_key_pem,
        fingerprint_sha256=public_key_fingerprint_sha256(public_key_pem),
        valid_from=NOW - timedelta(days=1),
        valid_to=valid_to,
        revoked_at=revoked_at,
        available_at=available_at,
    )
    registry = _registry(public_keys=(key,))
    payload = b"official release payload"
    inactive = verify_detached_signature(
        registry=registry,
        source_id=SOURCE_ID,
        source_identity_id=SOURCE_IDENTITY_ID,
        key_id=key_id,
        payload=payload,
        signature=private_key.sign(payload),
        observed_at=NOW,
        available_at=NOW,
        decision_time=NOW,
    )
    assert inactive.state is DetachedSignatureState.KEY_NOT_ACTIVE

    missing = verify_detached_signature(
        registry=registry,
        source_id=SOURCE_ID,
        source_identity_id=SOURCE_IDENTITY_ID,
        key_id="not-registered",
        payload=payload,
        signature=private_key.sign(payload),
        observed_at=NOW,
        available_at=NOW,
        decision_time=NOW,
    )
    assert missing.state is DetachedSignatureState.KEY_NOT_FOUND
