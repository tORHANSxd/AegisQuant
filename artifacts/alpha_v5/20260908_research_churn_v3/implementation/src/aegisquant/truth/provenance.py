"""Content-integrity projection kept explicitly separate from claim truth."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import ArtifactId
from aegisquant.domain.intelligence import RawContentEnvelope
from aegisquant.domain.time import ensure_utc
from aegisquant.truth.contracts import (
    C2paValidationState,
    C2paVerificationResult,
    ContentAuthenticityBinding,
    ContentIntegrityAssessment,
    ContentIntegrityState,
    OfficialIdentityAssessment,
    SourceCompromiseEvent,
)


def assess_content_integrity(
    verification: C2paVerificationResult,
    *,
    assessed_at: datetime,
    available_at: datetime,
) -> ContentIntegrityAssessment:
    """Project SDK provenance state without manufacturing a truth probability."""

    assessed = ensure_utc(assessed_at)
    available = ensure_utc(available_at)
    if verification.available_at > assessed or assessed > available:
        raise ValueError("AQ-TRUTH-CONTENT-INTEGRITY-TIME-ORDER")
    mapping = {
        C2paValidationState.TRUSTED: (
            ContentIntegrityState.VERIFIED_TRUSTED,
            "AQ-TRUTH-CONTENT-INTEGRITY-C2PA-TRUSTED",
        ),
        C2paValidationState.VALID: (
            ContentIntegrityState.VERIFIED_UNTRUSTED,
            "AQ-TRUTH-CONTENT-INTEGRITY-C2PA-VALID-UNTRUSTED",
        ),
        C2paValidationState.INVALID: (
            ContentIntegrityState.INVALID,
            "AQ-TRUTH-CONTENT-INTEGRITY-C2PA-INVALID",
        ),
        C2paValidationState.ABSENT: (
            ContentIntegrityState.NO_CREDENTIALS,
            "AQ-TRUTH-CONTENT-INTEGRITY-NO-CREDENTIALS-IS-NOT-FALSE",
        ),
        C2paValidationState.UNSUPPORTED: (
            ContentIntegrityState.UNSUPPORTED,
            "AQ-TRUTH-CONTENT-INTEGRITY-C2PA-UNSUPPORTED",
        ),
        C2paValidationState.SDK_UNAVAILABLE: (
            ContentIntegrityState.UNSUPPORTED,
            "AQ-TRUTH-CONTENT-INTEGRITY-C2PA-SDK-UNAVAILABLE",
        ),
        C2paValidationState.ERROR: (
            ContentIntegrityState.ERROR,
            "AQ-TRUTH-CONTENT-INTEGRITY-C2PA-ERROR",
        ),
    }
    state, reason = mapping[verification.validation_state]
    payload = {
        "asset_sha256": verification.asset_sha256,
        "c2pa_verification_id": str(verification.verification_id),
        "state": state.value,
        "credentials_present": verification.manifest_present,
        "tamper_detected": verification.tamper_detected,
        "reason": reason,
        "assessed_at": assessed.isoformat(),
        "available_at": available.isoformat(),
        "implies_claim_truth": False,
    }
    return ContentIntegrityAssessment(
        assessment_id=ArtifactId(canonical_sha256(payload)),
        asset_sha256=verification.asset_sha256,
        c2pa_verification_id=verification.verification_id,
        state=state,
        credentials_present=verification.manifest_present,
        tamper_detected=verification.tamper_detected,
        reason_codes=(reason,),
        assessed_at=assessed,
        available_at=available,
    )


def bind_content_authenticity(
    envelope: RawContentEnvelope,
    identity: OfficialIdentityAssessment,
    integrity: ContentIntegrityAssessment,
    *,
    compromise: SourceCompromiseEvent | None = None,
    available_at: datetime,
) -> ContentAuthenticityBinding:
    """Bind independent source and content signals to one immutable content revision."""

    available = ensure_utc(available_at)
    if envelope.source_identity_id != identity.source_identity_id:
        raise ValueError("AQ-TRUTH-BINDING-SOURCE-IDENTITY-MISMATCH")
    if envelope.raw_content_hash != integrity.asset_sha256:
        raise ValueError("AQ-TRUTH-BINDING-CONTENT-HASH-MISMATCH")
    if any(
        item_available > available
        for item_available in (
            envelope.available_time,
            identity.available_at,
            integrity.available_at,
        )
    ):
        raise ValueError("AQ-TRUTH-BINDING-FUTURE-EVIDENCE")
    if compromise is not None:
        if compromise.source_id != identity.source_id:
            raise ValueError("AQ-TRUTH-BINDING-COMPROMISE-SOURCE-MISMATCH")
        if compromise.available_at > available:
            raise ValueError("AQ-TRUTH-BINDING-FUTURE-COMPROMISE-EVIDENCE")

    reason_codes = (
        f"AQ-TRUTH-BINDING-IDENTITY-{identity.state.value}",
        f"AQ-TRUTH-BINDING-INTEGRITY-{integrity.state.value}",
        (
            f"AQ-TRUTH-BINDING-COMPROMISE-{compromise.status.value}"
            if compromise is not None
            else "AQ-TRUTH-BINDING-COMPROMISE-NOT-OBSERVED"
        ),
        "AQ-TRUTH-BINDING-CLAIM-TRUTH-INDEPENDENT",
    )
    payload = {
        "content_id": str(envelope.content_id),
        "source_identity_id": str(envelope.source_identity_id),
        "source_identity_assessment_id": str(identity.assessment_id),
        "content_integrity_assessment_id": str(integrity.assessment_id),
        "source_compromise_event_id": (
            str(compromise.event_id) if compromise is not None else None
        ),
        "asset_sha256": integrity.asset_sha256,
        "identity_state": identity.state.value,
        "integrity_state": integrity.state.value,
        "source_compromise_status": (compromise.status.value if compromise is not None else None),
        "reason_codes": reason_codes,
        "available_at": available.isoformat(),
        "claim_truth_implied": False,
    }
    return ContentAuthenticityBinding(
        binding_id=ArtifactId(canonical_sha256(payload)),
        content_id=envelope.content_id,
        source_identity_id=envelope.source_identity_id,
        source_identity_assessment_id=identity.assessment_id,
        content_integrity_assessment_id=integrity.assessment_id,
        source_compromise_event_id=(compromise.event_id if compromise is not None else None),
        asset_sha256=integrity.asset_sha256,
        identity_state=identity.state,
        integrity_state=integrity.state,
        source_compromise_status=(compromise.status if compromise is not None else None),
        reason_codes=reason_codes,
        available_at=available,
    )


class ContentIntegrityStore:
    """Append-only point-in-time view of integrity assessments."""

    def __init__(self) -> None:
        self._history: dict[str, list[ContentIntegrityAssessment]] = defaultdict(list)

    def apply(self, assessment: ContentIntegrityAssessment) -> None:
        history = self._history[assessment.asset_sha256]
        if history and assessment == history[-1]:
            return
        if any(item.assessment_id == assessment.assessment_id for item in history):
            raise ValueError("AQ-TRUTH-CONTENT-INTEGRITY-ASSESSMENT-ID-CONFLICT")
        if history and assessment.available_at < history[-1].available_at:
            raise ValueError("AQ-TRUTH-CONTENT-INTEGRITY-TIME-REGRESSION")
        history.append(assessment)

    def history(self, asset_sha256: str) -> tuple[ContentIntegrityAssessment, ...]:
        return tuple(self._history.get(asset_sha256, ()))

    def as_of(
        self, asset_sha256: str, *, decision_time: datetime
    ) -> ContentIntegrityAssessment | None:
        decision = ensure_utc(decision_time)
        visible = [
            item
            for item in self._history.get(asset_sha256, ())
            if item.assessed_at <= decision and item.available_at <= decision
        ]
        return (
            max(visible, key=lambda item: (item.available_at, str(item.assessment_id)))
            if visible
            else None
        )
