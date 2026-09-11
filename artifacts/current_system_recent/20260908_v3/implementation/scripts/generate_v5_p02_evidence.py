"""Generate or verify deterministic V5-P02 source-provenance acceptance evidence."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegisquant.domain.identifiers import (
    ArtifactId,
    ContentId,
    ProviderId,
    ProviderNativeId,
    SourceId,
    SourceIdentityId,
    SourcePolicyId,
)
from aegisquant.domain.intelligence import (
    ContentType,
    QualityState,
    RawContentEnvelope,
    RightsState,
)
from aegisquant.domain.time import FixedClock
from aegisquant.truth.c2pa import C2paPythonBackend, C2paVerifier
from aegisquant.truth.contracts import (
    C2paValidationState,
    ContentIntegrityState,
    DetachedSignatureState,
    IdentityFactor,
    OfficialIdentityObservation,
    OfficialIdentityState,
    OfficialPublicKey,
    PublicKeyAlgorithm,
    SourceCompromiseEvent,
    SourceCompromiseStatus,
)
from aegisquant.truth.identity import assess_official_identity, verify_detached_signature
from aegisquant.truth.provenance import assess_content_integrity, bind_content_authenticity
from aegisquant.truth.source_registry import SourceRegistry, public_key_fingerprint_sha256
from tests.v5_p02.helpers import PNG_BYTES, build_c2pa_assets

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT: Final = ROOT / "reports/v5/P02/SOURCE_PROVENANCE_EVIDENCE.json"
REGISTRY_PATH: Final = ROOT / "data/catalogs/v5_source_registry.yaml"
BASE_TIME: Final = datetime(2026, 9, 2, 16, 30, tzinfo=UTC)
SEC_SOURCE_ID: Final = SourceId("us-sec")
SEC_IDENTITY_ID: Final = SourceIdentityId("source-identity:us-sec")


def _observation(**changes: object) -> OfficialIdentityObservation:
    payload: dict[str, object] = {
        "source_id": SEC_SOURCE_ID,
        "source_identity_id": SEC_IDENTITY_ID,
        "observed_url": "https://www.sec.gov/news/pressreleases.rss",
        "api_endpoint": "https://www.sec.gov/news/pressreleases.rss",
        "observed_at": BASE_TIME,
        "available_at": BASE_TIME,
    }
    payload.update(changes)
    return OfficialIdentityObservation.model_validate(payload)


def _registry_with_test_key(registry: SourceRegistry) -> tuple[SourceRegistry, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public_key_pem = (
        private_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    public_key = OfficialPublicKey(
        key_id="v5-p02-development-key",
        algorithm=PublicKeyAlgorithm.ED25519,
        public_key_pem=public_key_pem,
        fingerprint_sha256=public_key_fingerprint_sha256(public_key_pem),
        valid_from=registry.entry_as_of(SEC_SOURCE_ID, decision_time=BASE_TIME).valid_from,
        available_at=BASE_TIME,
    )
    entries = tuple(
        entry.model_copy(update={"public_keys": (public_key,)})
        if entry.source_id == SEC_SOURCE_ID
        else entry
        for entry in registry.document.entries
    )
    document = registry.document.model_copy(update={"available_at": BASE_TIME, "entries": entries})
    return SourceRegistry.from_document(document), private_key


def build_payload() -> dict[str, object]:
    registry = SourceRegistry.from_yaml(REGISTRY_PATH)
    authentic = assess_official_identity(
        registry=registry,
        observation=_observation(),
        decision_time=BASE_TIME,
    )
    spoofed = assess_official_identity(
        registry=registry,
        observation=_observation(observed_url="https://www.sec.gov.attacker.example/news"),
        decision_time=BASE_TIME,
    )
    homograph = assess_official_identity(
        registry=registry,
        observation=_observation(observed_url="https://www.sеc.gov/news/pressreleases.rss"),
        decision_time=BASE_TIME,
    )
    domain_only = assess_official_identity(
        registry=registry,
        observation=_observation(api_endpoint=None),
        decision_time=BASE_TIME,
    )

    keyed_registry, private_key = _registry_with_test_key(registry)
    payload = b"V5-P02 deterministic official release"
    signature = private_key.sign(payload)
    valid_signature = verify_detached_signature(
        registry=keyed_registry,
        source_id=SEC_SOURCE_ID,
        source_identity_id=SEC_IDENTITY_ID,
        key_id="v5-p02-development-key",
        payload=payload,
        signature=signature,
        observed_at=BASE_TIME,
        available_at=BASE_TIME,
        decision_time=BASE_TIME,
    )
    invalid_signature = verify_detached_signature(
        registry=keyed_registry,
        source_id=SEC_SOURCE_ID,
        source_identity_id=SEC_IDENTITY_ID,
        key_id="v5-p02-development-key",
        payload=payload + b" tampered",
        signature=signature,
        observed_at=BASE_TIME,
        available_at=BASE_TIME,
        decision_time=BASE_TIME,
    )
    signature_identity = assess_official_identity(
        registry=keyed_registry,
        observation=_observation(
            observed_url=None,
            api_endpoint=None,
            detached_signature_verification_id=valid_signature.verification_id,
        ),
        decision_time=BASE_TIME,
        signature_verifications=(valid_signature,),
    )

    with tempfile.TemporaryDirectory(prefix="aegisquant-v5-p02-") as temporary:
        temporary_path = Path(temporary)
        plain_path = temporary_path / "plain.png"
        plain_path.write_bytes(PNG_BYTES)
        signed_path, tampered_path, root_pem = build_c2pa_assets(temporary_path)
        plain_c2pa = C2paVerifier(clock=FixedClock(BASE_TIME)).verify_file(plain_path)
        c2pa_verifier = C2paVerifier(
            backend=C2paPythonBackend(user_trust_anchors_pem=root_pem),
            clock=FixedClock(BASE_TIME),
        )
        valid_c2pa = c2pa_verifier.verify_file(signed_path)
        invalid_c2pa = c2pa_verifier.verify_file(tampered_path)

    no_credentials = assess_content_integrity(
        plain_c2pa,
        assessed_at=BASE_TIME,
        available_at=BASE_TIME,
    )
    compromised = SourceCompromiseEvent(
        event_id=ArtifactId("v5-p02-compromised-source:v1"),
        source_id=SEC_SOURCE_ID,
        version=1,
        status=SourceCompromiseStatus.COMPROMISED,
        reason_codes=("DEVELOPMENT_ACCOUNT_TAKEOVER_SCENARIO",),
        effective_at=BASE_TIME,
        observed_at=BASE_TIME,
        available_at=BASE_TIME,
    )
    envelope = RawContentEnvelope(
        content_id=ContentId("v5-p02-compromised-content"),
        provider_id=ProviderId("v5-p02-provider"),
        provider_native_id=ProviderNativeId("v5-p02-native-content"),
        source_identity_id=SEC_IDENTITY_ID,
        content_type=ContentType.ANNOUNCEMENT,
        canonical_url="https://www.sec.gov/news/pressreleases.rss",
        published_time=BASE_TIME,
        first_observed_time=BASE_TIME,
        available_time=BASE_TIME,
        ingest_time=BASE_TIME,
        language="en",
        raw_content_hash=no_credentials.asset_sha256,
        revision=1,
        source_policy_id=SourcePolicyId("v5-p02-source-policy"),
        rights_state=RightsState.ALLOWED,
        quality_state=QualityState.GOOD,
    )
    binding = bind_content_authenticity(
        envelope,
        authentic,
        no_credentials,
        compromise=compromised,
        available_at=BASE_TIME,
    )

    checks = {
        "registry_is_versioned_and_content_addressed": (
            registry.document.registry_version == 1 and len(registry.content_hash()) == 64
        ),
        "unmeasured_source_history_remains_null": all(
            entry.historical_accuracy is None
            and entry.historical_correction_rate is None
            and entry.historical_retraction_rate is None
            and entry.first_report_latency_seconds is None
            for entry in registry.document.entries
        ),
        "official_domain_plus_exact_endpoint_authenticates": (
            authentic.state is OfficialIdentityState.AUTHENTIC
        ),
        "spoof_domain_is_rejected": spoofed.state is OfficialIdentityState.REJECTED,
        "unicode_homograph_is_rejected": homograph.state is OfficialIdentityState.REJECTED,
        "domain_string_alone_is_insufficient": (
            domain_only.state is OfficialIdentityState.INSUFFICIENT_EVIDENCE
        ),
        "tier_is_prior_only": authentic.tier_is_prior_only,
        "detached_signature_validates": (
            valid_signature.state is DetachedSignatureState.VALID
            and signature_identity.state is OfficialIdentityState.AUTHENTIC
            and signature_identity.matched_factors == (IdentityFactor.DETACHED_SIGNATURE,)
        ),
        "tampered_detached_signature_is_invalid": (
            invalid_signature.state is DetachedSignatureState.INVALID
        ),
        "no_c2pa_is_unknown_not_false": (
            plain_c2pa.validation_state is C2paValidationState.ABSENT
            and no_credentials.state is ContentIntegrityState.NO_CREDENTIALS
            and no_credentials.tamper_detected is None
        ),
        "official_sdk_validates_signature_trust_and_binding": (
            valid_c2pa.validation_state is C2paValidationState.TRUSTED
            and valid_c2pa.signature_valid is True
            and valid_c2pa.trust_list_valid is True
            and valid_c2pa.content_binding_valid is True
        ),
        "tampered_c2pa_is_invalid": (
            invalid_c2pa.validation_state is C2paValidationState.INVALID
            and invalid_c2pa.tamper_detected is True
        ),
        "c2pa_valid_does_not_imply_claim_true": valid_c2pa.claim_truth_implied is False,
        "authentic_source_can_be_compromised": (
            binding.identity_state is OfficialIdentityState.AUTHENTIC
            and binding.source_compromise_status is SourceCompromiseStatus.COMPROMISED
            and binding.claim_truth_implied is False
        ),
        "remote_manifest_and_ocsp_fetch_are_disabled": (
            valid_c2pa.remote_manifest_fetch_enabled is False
            and valid_c2pa.ocsp_fetch_enabled is False
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"V5-P02 acceptance check failed: {checks}")

    acceptance_traceability = {
        "registry_is_versioned_and_content_addressed": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_checked_in_registry_is_versioned_and_hash_order_invariant"
        ),
        "unmeasured_source_history_remains_null": (
            "tests/v5_p02/test_v5_p02_phase_evidence.py::"
            "test_v5_p02_source_provenance_evidence_is_complete"
        ),
        "official_domain_plus_exact_endpoint_authenticates": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_spoof_homograph_and_domain_only_evidence_fail_closed"
        ),
        "spoof_domain_is_rejected": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_spoof_homograph_and_domain_only_evidence_fail_closed"
        ),
        "unicode_homograph_is_rejected": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_spoof_homograph_and_domain_only_evidence_fail_closed"
        ),
        "domain_string_alone_is_insufficient": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_spoof_homograph_and_domain_only_evidence_fail_closed"
        ),
        "tier_is_prior_only": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_spoof_homograph_and_domain_only_evidence_fail_closed"
        ),
        "detached_signature_validates": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_detached_signature_binds_source_identity_and_detects_tampering"
        ),
        "tampered_detached_signature_is_invalid": (
            "tests/v5_p02/test_source_registry_identity.py::"
            "test_detached_signature_binds_source_identity_and_detects_tampering"
        ),
        "no_c2pa_is_unknown_not_false": (
            "tests/v5_p02/test_c2pa_content_integrity.py::"
            "test_no_c2pa_is_unknown_integrity_not_false"
        ),
        "official_sdk_validates_signature_trust_and_binding": (
            "tests/v5_p02/test_c2pa_content_integrity.py::"
            "test_official_sdk_validates_signature_trust_binding_ai_assertion_and_tamper"
        ),
        "tampered_c2pa_is_invalid": (
            "tests/v5_p02/test_c2pa_content_integrity.py::"
            "test_official_sdk_validates_signature_trust_binding_ai_assertion_and_tamper"
        ),
        "c2pa_valid_does_not_imply_claim_true": (
            "tests/v5_p02/test_c2pa_content_integrity.py::"
            "test_valid_c2pa_does_not_promote_claim_truth"
        ),
        "authentic_source_can_be_compromised": (
            "tests/v5_p02/test_c2pa_content_integrity.py::"
            "test_content_binding_preserves_authentic_but_compromised_source_state"
        ),
        "remote_manifest_and_ocsp_fetch_are_disabled": (
            "tests/v5_p02/test_c2pa_content_integrity.py::"
            "test_official_sdk_validates_signature_trust_binding_ai_assertion_and_tamper"
        ),
    }
    if set(acceptance_traceability) != set(checks):
        raise RuntimeError("V5-P02 acceptance traceability is incomplete")

    return {
        "schema_version": "v5-p02-source-provenance-evidence-v1",
        "phase": "V5-P02",
        "generated_from_fixed_clock": BASE_TIME.isoformat(),
        "evidence_tier": "DEVELOPMENT",
        "alpha_promotion_eligible": False,
        "calibrated_truth_model_present": False,
        "live_trading_locked": True,
        "source_registry": {
            "path": REGISTRY_PATH.relative_to(ROOT).as_posix(),
            "registry_version": registry.document.registry_version,
            "entry_count": len(registry.document.entries),
            "content_sha256": registry.content_hash(),
        },
        "c2pa_runtime": {
            "implementation": "official c2pa-python SDK backed by c2pa-rs",
            "package_version": valid_c2pa.package_version,
            "sdk_version": valid_c2pa.sdk_version,
            "target_specification": "C2PA 2.x",
            "preferred_specification": "C2PA 2.3",
            "fixture_trust": "EPHEMERAL_SELF_GENERATED_DEVELOPMENT_ROOT",
            "timestamp_authority_present": False,
            "remote_manifest_fetch_enabled": False,
            "ocsp_fetch_enabled": False,
        },
        "observed_states": {
            "official_identity": authentic.state.value,
            "spoof_identity": spoofed.state.value,
            "domain_only_identity": domain_only.state.value,
            "valid_detached_signature": valid_signature.state.value,
            "invalid_detached_signature": invalid_signature.state.value,
            "no_c2pa": plain_c2pa.validation_state.value,
            "valid_c2pa": valid_c2pa.validation_state.value,
            "tampered_c2pa": invalid_c2pa.validation_state.value,
            "compromised_official_identity": binding.identity_state.value,
            "compromise_status": compromised.status.value,
        },
        "checks": checks,
        "acceptance_traceability": acceptance_traceability,
        "limitations": [
            "Development fixtures are not C2PA conformance certification.",
            "The test certificate chain is self-generated and trusted only by an injected root.",
            "No production trust-list refresh, OCSP, or remote-manifest retrieval is enabled.",
            "Source reliability and claim-truth probabilities remain uncalibrated.",
        ],
        "result": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(build_payload(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"V5-P02 evidence is stale: {OUTPUT.relative_to(ROOT).as_posix()}")
        print("verified deterministic V5-P02 source-provenance evidence")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8", newline="\n")
    print("wrote deterministic V5-P02 source-provenance evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
