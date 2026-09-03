"""Official SDK integration and the C2PA/content-truth separation boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisquant.domain.identifiers import (
    ArtifactId,
    ClaimId,
    ContentId,
    ProviderId,
    ProviderNativeId,
    SourceDocumentId,
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
from aegisquant.domain.truth import ClaimType, TruthAssessment, TruthAssessmentScope, TruthState
from aegisquant.truth.c2pa import (
    C2paBackend,
    C2paInvalidManifestError,
    C2paPythonBackend,
    C2paRuntimeError,
    C2paSdkPayload,
    C2paSdkUnavailableError,
    C2paUnsupportedError,
    C2paVerifier,
)
from aegisquant.truth.contracts import (
    C2paSpecCompatibility,
    C2paValidationState,
    C2paVerificationResult,
    CertificateState,
    ContentIntegrityAssessment,
    ContentIntegrityState,
    IdentityFactor,
    OfficialIdentityAssessment,
    OfficialIdentityState,
    SourceCompromiseEvent,
    SourceCompromiseStatus,
)
from aegisquant.truth.provenance import (
    ContentIntegrityStore,
    assess_content_integrity,
    bind_content_authenticity,
)
from tests.v5_p02.helpers import PNG_BYTES, build_c2pa_assets

NOW = datetime(2026, 9, 2, 17, tzinfo=UTC)


def test_official_sdk_validates_signature_trust_binding_ai_assertion_and_tamper(
    tmp_path: Path,
) -> None:
    signed, tampered, root_pem = build_c2pa_assets(tmp_path)
    verifier = C2paVerifier(
        backend=C2paPythonBackend(user_trust_anchors_pem=root_pem),
        clock=FixedClock(NOW),
    )
    valid = verifier.verify_file(signed)
    assert valid.package_version == "0.37.8"
    assert valid.sdk_version == "0.90.15"
    assert valid.validation_state is C2paValidationState.TRUSTED
    assert valid.signature_valid is True
    assert valid.trust_list_valid is True
    assert valid.content_binding_valid is True
    assert valid.tamper_detected is False
    assert valid.generator_information == ("AegisQuant V5-P02@1.0.0",)
    assert any("trainedAlgorithmicMedia" in item for item in valid.ai_assertions)
    assert valid.remote_manifest_fetch_enabled is False
    assert valid.ocsp_fetch_enabled is False

    altered = verifier.verify_file(tampered)
    assert altered.validation_state is C2paValidationState.INVALID
    assert altered.content_binding_valid is False
    assert altered.tamper_detected is True


def test_no_c2pa_is_unknown_integrity_not_false(tmp_path: Path) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    verification = C2paVerifier(clock=FixedClock(NOW)).verify_file(plain)
    assert verification.validation_state is C2paValidationState.ABSENT
    assert verification.manifest_present is False
    assert verification.tamper_detected is None

    integrity = assess_content_integrity(
        verification,
        assessed_at=NOW,
        available_at=NOW,
    )
    assert integrity.state is ContentIntegrityState.NO_CREDENTIALS
    assert integrity.credentials_present is False
    assert integrity.tamper_detected is None
    assert integrity.implies_claim_truth is False


def test_valid_c2pa_does_not_promote_claim_truth(tmp_path: Path) -> None:
    signed, _, root_pem = build_c2pa_assets(tmp_path)
    verification = C2paVerifier(
        backend=C2paPythonBackend(user_trust_anchors_pem=root_pem),
        clock=FixedClock(NOW),
    ).verify_file(signed)
    integrity = assess_content_integrity(
        verification,
        assessed_at=NOW,
        available_at=NOW,
    )
    truth = TruthAssessment(
        assessment_id=ArtifactId("truth-independent-from-c2pa"),
        claim_id=ClaimId("claim-c2pa-can-still-be-false"),
        claim_type=ClaimType.FACT,
        assessment_scope=TruthAssessmentScope.CLAIM_TRUTH,
        source_document_ids=(SourceDocumentId("document-c2pa"),),
        source_revision_ids=(ArtifactId("revision-c2pa"),),
        source_identity_probability=Decimal("1"),
        content_integrity_probability=Decimal("1"),
        claim_truth_probability=Decimal("0"),
        claim_current_probability=Decimal("1"),
        evidence_independence_probability=Decimal("0"),
        manipulation_probability=Decimal("0"),
        revision_probability=Decimal("0"),
        source_compromised_probability=Decimal("0"),
        independent_evidence_count=0,
        evidence_dependency_score=Decimal("1"),
        contradiction_probability=Decimal("1"),
        calibration_bucket="DEVELOPMENT_UNCALIBRATED",
        truth_state=TruthState.CONTRADICTED,
        reason_codes=("C2PA_PROVENANCE_IS_NOT_CLAIM_TRUTH",),
        evidence_graph_hash="0" * 64,
        model_version="none",
        policy_version="v5-p02",
        assessed_at=NOW,
        available_at=NOW,
    )
    assert integrity.state is ContentIntegrityState.VERIFIED_TRUSTED
    assert integrity.implies_claim_truth is False
    assert truth.content_integrity_probability == Decimal("1")
    assert truth.claim_truth_probability == Decimal("0")


class _UnavailableBackend:
    def verify(self, asset_path: Path) -> C2paSdkPayload | None:
        del asset_path
        raise C2paSdkUnavailableError("simulated unavailable SDK")


class _UnsupportedBackend:
    def verify(self, asset_path: Path) -> C2paSdkPayload | None:
        del asset_path
        raise C2paUnsupportedError("simulated unsupported asset")


class _InvalidManifestBackend:
    def verify(self, asset_path: Path) -> C2paSdkPayload | None:
        del asset_path
        raise C2paInvalidManifestError("simulated malformed manifest")


class _RuntimeFailureBackend:
    def verify(self, asset_path: Path) -> C2paSdkPayload | None:
        del asset_path
        raise C2paRuntimeError("simulated verifier failure")


class _V23PayloadBackend:
    def verify(self, asset_path: Path) -> C2paSdkPayload | None:
        del asset_path
        return C2paSdkPayload(
            package_version="0.37.8",
            sdk_version="0.90.15",
            manifest_store={
                "active_manifest": "urn:c2pa:test",
                "manifests": {
                    "urn:c2pa:test": {
                        "specVersion": "2.3.0",
                        "claim_generator_info": [{"name": "fixture", "version": "1"}],
                        "assertions": [],
                    }
                },
            },
            validation_state="Trusted",
            validation_results={
                "activeManifest": {
                    "success": [
                        {"code": "claimSignature.validated"},
                        {"code": "assertion.dataHash.match"},
                        {"code": "signingCredential.trusted"},
                    ],
                    "informational": [],
                    "failure": [],
                }
            },
        )


def test_sdk_failure_is_fail_closed_and_2_3_metadata_is_preserved(tmp_path: Path) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    unavailable = C2paVerifier(
        backend=_UnavailableBackend(),
        clock=FixedClock(NOW),
    ).verify_file(plain)
    assert unavailable.validation_state is C2paValidationState.SDK_UNAVAILABLE
    assert unavailable.manifest_present is None

    versioned = C2paVerifier(
        backend=_V23PayloadBackend(),
        clock=FixedClock(NOW),
    ).verify_file(plain)
    assert versioned.specification_version == "2.3.0"
    assert versioned.spec_compatibility is C2paSpecCompatibility.PREFERRED_2_3


@pytest.mark.parametrize(
    ("backend", "state", "manifest_present", "reason_code"),
    (
        (
            _UnsupportedBackend(),
            C2paValidationState.UNSUPPORTED,
            None,
            "AQ-TRUTH-C2PA-ASSET-UNSUPPORTED",
        ),
        (
            _InvalidManifestBackend(),
            C2paValidationState.INVALID,
            True,
            "AQ-TRUTH-C2PA-MANIFEST-INVALID",
        ),
        (
            _RuntimeFailureBackend(),
            C2paValidationState.ERROR,
            None,
            "AQ-TRUTH-C2PA-VERIFICATION-ERROR",
        ),
    ),
)
def test_sdk_error_classes_are_distinct_and_fail_closed(
    tmp_path: Path,
    backend: C2paBackend,
    state: C2paValidationState,
    manifest_present: bool | None,
    reason_code: str,
) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    result = C2paVerifier(backend=backend, clock=FixedClock(NOW)).verify_file(plain)
    assert result.validation_state is state
    assert result.manifest_present is manifest_present
    assert result.validation_codes == (reason_code,)
    assert result.claim_truth_implied is False


class _CredentialFailureBackend:
    def __init__(self, failure_code: str) -> None:
        self.failure_code = failure_code

    def verify(self, asset_path: Path) -> C2paSdkPayload | None:
        del asset_path
        return C2paSdkPayload(
            package_version="0.37.8",
            sdk_version="0.90.15",
            manifest_store={
                "active_manifest": "urn:c2pa:test",
                "manifests": {"urn:c2pa:test": {"specVersion": "2.3.0"}},
            },
            validation_state="Invalid",
            validation_results={
                "activeManifest": {
                    "success": [
                        {"code": "claimSignature.validated"},
                        {"code": "assertion.dataHash.match"},
                    ],
                    "failure": [{"code": self.failure_code}],
                }
            },
        )


@pytest.mark.parametrize(
    ("failure_code", "certificate_state"),
    (
        ("signingCredential.outsideValidity", CertificateState.EXPIRED),
        ("signingCredential.revoked", CertificateState.REVOKED),
    ),
)
def test_credential_failures_do_not_masquerade_as_asset_tampering(
    tmp_path: Path,
    failure_code: str,
    certificate_state: CertificateState,
) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    result = C2paVerifier(
        backend=_CredentialFailureBackend(failure_code),
        clock=FixedClock(NOW),
    ).verify_file(plain)
    assert result.validation_state is C2paValidationState.INVALID
    assert result.signature_valid is True
    assert result.content_binding_valid is True
    assert result.certificate_state is certificate_state
    assert result.tamper_detected is False


def test_c2pa_and_integrity_contracts_reject_inconsistent_states(tmp_path: Path) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    absent = C2paVerifier(clock=FixedClock(NOW)).verify_file(plain)
    absent_with_false_tamper = json.loads(absent.model_dump_json())
    absent_with_false_tamper["tamper_detected"] = False
    with pytest.raises(ValidationError, match="absent C2PA has unknown validation signals"):
        C2paVerificationResult.model_validate_json(json.dumps(absent_with_false_tamper))

    untrusted_as_trusted = json.loads(absent.model_dump_json())
    untrusted_as_trusted.update(
        {
            "validation_state": C2paValidationState.TRUSTED,
            "manifest_present": True,
            "signature_valid": True,
            "trust_list_valid": True,
            "content_binding_valid": True,
            "tamper_detected": False,
            "certificate_state": CertificateState.VALID_UNTRUSTED,
        }
    )
    with pytest.raises(ValidationError, match="trusted C2PA requires trusted signing credentials"):
        C2paVerificationResult.model_validate_json(json.dumps(untrusted_as_trusted))

    integrity = assess_content_integrity(absent, assessed_at=NOW, available_at=NOW)
    no_credentials_with_false_tamper = json.loads(integrity.model_dump_json())
    no_credentials_with_false_tamper["tamper_detected"] = False
    with pytest.raises(ValidationError, match="no credentials is unknown integrity"):
        ContentIntegrityAssessment.model_validate_json(json.dumps(no_credentials_with_false_tamper))

    unverified_as_verified = json.loads(integrity.model_dump_json())
    unverified_as_verified.update(
        {
            "state": ContentIntegrityState.VERIFIED_TRUSTED,
            "credentials_present": False,
            "tamper_detected": False,
        }
    )
    with pytest.raises(ValidationError, match="verified integrity requires present credentials"):
        ContentIntegrityAssessment.model_validate_json(json.dumps(unverified_as_verified))


def test_verification_available_time_cannot_precede_verification(tmp_path: Path) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    verifier = C2paVerifier(clock=FixedClock(NOW))
    with pytest.raises(ValueError, match="AQ-TRUTH-C2PA-RESULT-TIME-ORDER"):
        verifier.verify_file(plain, available_at=NOW - timedelta(microseconds=1))
    result = verifier.verify_file(plain, available_at=NOW + timedelta(seconds=1))
    assert result.available_at == NOW + timedelta(seconds=1)


def test_content_integrity_store_is_append_only_and_point_in_time(tmp_path: Path) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    verification = C2paVerifier(clock=FixedClock(NOW)).verify_file(plain)
    assessment = assess_content_integrity(
        verification,
        assessed_at=NOW,
        available_at=NOW,
    )
    store = ContentIntegrityStore()
    store.apply(assessment)
    store.apply(assessment)
    assert store.as_of(assessment.asset_sha256, decision_time=NOW) == assessment


def test_content_binding_preserves_authentic_but_compromised_source_state(
    tmp_path: Path,
) -> None:
    plain = tmp_path / "plain.png"
    plain.write_bytes(PNG_BYTES)
    verification = C2paVerifier(clock=FixedClock(NOW)).verify_file(plain)
    integrity = assess_content_integrity(
        verification,
        assessed_at=NOW,
        available_at=NOW,
    )
    source_id = SourceId("official-but-compromised")
    source_identity_id = SourceIdentityId("identity:official-but-compromised")
    identity = OfficialIdentityAssessment(
        assessment_id=ArtifactId("identity-assessment:official-but-compromised"),
        source_id=source_id,
        source_identity_id=source_identity_id,
        registry_entry_id=ArtifactId("registry-entry:official-but-compromised"),
        state=OfficialIdentityState.AUTHENTIC,
        matched_factors=(IdentityFactor.SOCIAL_ACCOUNT,),
        reason_codes=("OFFICIAL_ACCOUNT_ID_MATCH",),
        observed_at=NOW,
        available_at=NOW,
    )
    compromise = SourceCompromiseEvent(
        event_id=ArtifactId("compromise:official-but-compromised:v1"),
        source_id=source_id,
        version=1,
        status=SourceCompromiseStatus.COMPROMISED,
        reason_codes=("ACCOUNT_TAKEOVER_CONFIRMED",),
        effective_at=NOW,
        observed_at=NOW,
        available_at=NOW,
    )
    envelope = RawContentEnvelope(
        content_id=ContentId("content:official-but-compromised"),
        provider_id=ProviderId("provider:test"),
        provider_native_id=ProviderNativeId("native:test"),
        source_identity_id=source_identity_id,
        content_type=ContentType.ANNOUNCEMENT,
        canonical_url="https://official.example/announcement",
        published_time=NOW,
        first_observed_time=NOW,
        available_time=NOW,
        ingest_time=NOW,
        language="en",
        raw_content_hash=verification.asset_sha256,
        revision=1,
        source_policy_id=SourcePolicyId("source-policy:v5-p02"),
        rights_state=RightsState.ALLOWED,
        quality_state=QualityState.GOOD,
    )
    binding = bind_content_authenticity(
        envelope,
        identity,
        integrity,
        compromise=compromise,
        available_at=NOW,
    )
    assert binding.identity_state is OfficialIdentityState.AUTHENTIC
    assert binding.integrity_state is ContentIntegrityState.NO_CREDENTIALS
    assert binding.source_compromise_status is SourceCompromiseStatus.COMPROMISED
    assert binding.claim_truth_implied is False

    future = NOW + timedelta(seconds=1)
    with pytest.raises(ValueError, match="AQ-TRUTH-BINDING-SOURCE-IDENTITY-MISMATCH"):
        bind_content_authenticity(
            envelope.model_copy(
                update={"source_identity_id": SourceIdentityId("identity:wrong-source")}
            ),
            identity,
            integrity,
            available_at=NOW,
        )
    with pytest.raises(ValueError, match="AQ-TRUTH-BINDING-CONTENT-HASH-MISMATCH"):
        bind_content_authenticity(
            envelope.model_copy(update={"raw_content_hash": "f" * 64}),
            identity,
            integrity,
            available_at=NOW,
        )
    with pytest.raises(ValueError, match="AQ-TRUTH-BINDING-FUTURE-EVIDENCE"):
        bind_content_authenticity(
            envelope.model_copy(update={"available_time": future, "ingest_time": future}),
            identity,
            integrity,
            available_at=NOW,
        )
    with pytest.raises(ValueError, match="AQ-TRUTH-BINDING-FUTURE-EVIDENCE"):
        bind_content_authenticity(
            envelope,
            identity.model_copy(update={"available_at": future}),
            integrity,
            available_at=NOW,
        )
    with pytest.raises(ValueError, match="AQ-TRUTH-BINDING-FUTURE-EVIDENCE"):
        bind_content_authenticity(
            envelope,
            identity,
            integrity.model_copy(update={"available_at": future}),
            available_at=NOW,
        )
    with pytest.raises(ValueError, match="AQ-TRUTH-BINDING-COMPROMISE-SOURCE-MISMATCH"):
        bind_content_authenticity(
            envelope,
            identity,
            integrity,
            compromise=compromise.model_copy(update={"source_id": SourceId("wrong-source")}),
            available_at=NOW,
        )
    with pytest.raises(ValueError, match="AQ-TRUTH-BINDING-FUTURE-COMPROMISE-EVIDENCE"):
        bind_content_authenticity(
            envelope,
            identity,
            integrity,
            compromise=compromise.model_copy(update={"available_at": future}),
            available_at=NOW,
        )
