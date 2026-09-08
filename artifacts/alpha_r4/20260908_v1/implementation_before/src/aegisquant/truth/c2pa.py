"""Fail-closed adapter over the official c2pa-python / c2pa-rs verifier."""

from __future__ import annotations

import importlib
import json
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, cast

from aegisquant.data.hashing import canonical_sha256, sha256_file
from aegisquant.domain.identifiers import ArtifactId
from aegisquant.domain.time import Clock, SystemClock, ensure_utc
from aegisquant.truth.contracts import (
    C2paSpecCompatibility,
    C2paValidationState,
    C2paVerificationResult,
    CertificateState,
)


class C2paSdkUnavailableError(RuntimeError):
    pass


class C2paUnsupportedError(RuntimeError):
    pass


class C2paInvalidManifestError(RuntimeError):
    pass


class C2paRuntimeError(RuntimeError):
    pass


class _ManagedContext(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class _Reader(_ManagedContext, Protocol):
    def json(self) -> str: ...

    def get_validation_state(self) -> str | None: ...

    def get_validation_results(self) -> dict[str, object] | None: ...


class _ContextFactory(Protocol):
    def from_dict(self, config: dict[str, object]) -> _ManagedContext: ...


class _ReaderFactory(Protocol):
    def try_create(
        self,
        format_or_path: Path,
        stream: object | None = None,
        manifest_data: object | None = None,
        context: object | None = None,
    ) -> _Reader | None: ...


class _ErrorNamespace(Protocol):
    ManifestNotFound: type[Exception]
    NotSupported: type[Exception]
    RemoteManifest: type[Exception]
    Verify: type[Exception]
    Signature: type[Exception]
    Manifest: type[Exception]
    Json: type[Exception]
    Decoding: type[Exception]


class _C2paModule(Protocol):
    __version__: str
    Context: _ContextFactory
    Reader: _ReaderFactory
    C2paError: _ErrorNamespace

    def sdk_version(self) -> str: ...


@dataclass(frozen=True, slots=True)
class C2paSdkPayload:
    package_version: str
    sdk_version: str
    manifest_store: Mapping[str, object]
    validation_state: str | None
    validation_results: Mapping[str, object]


class C2paBackend(Protocol):
    def verify(self, asset_path: Path) -> C2paSdkPayload | None: ...


def _json_mapping(raw: str, *, field_name: str) -> dict[str, object]:
    decoded: object = json.loads(raw)
    if not isinstance(decoded, dict):
        raise C2paInvalidManifestError(f"{field_name} is not a JSON object")
    decoded_mapping = cast(dict[object, object], decoded)
    if not all(isinstance(key, str) for key in decoded_mapping):
        raise C2paInvalidManifestError(f"{field_name} keys must be strings")
    return cast(dict[str, object], decoded_mapping)


@dataclass(frozen=True, slots=True)
class C2paPythonBackend:
    """Official SDK boundary with network fetching disabled by construction."""

    module_name: str = "c2pa"
    user_trust_anchors_pem: str | None = None

    def _settings(self) -> dict[str, object]:
        settings: dict[str, object] = {
            "version": 1,
            "verify": {
                "verify_after_reading": True,
                "verify_trust": True,
                "verify_timestamp_trust": True,
                "ocsp_fetch": False,
                "remote_manifest_fetch": False,
            },
        }
        if self.user_trust_anchors_pem is not None:
            settings["trust"] = {"user_anchors": self.user_trust_anchors_pem}
        return settings

    def verify(self, asset_path: Path) -> C2paSdkPayload | None:
        try:
            module = cast(_C2paModule, importlib.import_module(self.module_name))
        except ModuleNotFoundError as error:
            raise C2paSdkUnavailableError("c2pa-python is unavailable") from error

        try:
            with module.Context.from_dict(self._settings()) as context:
                reader = module.Reader.try_create(asset_path, context=context)
                if reader is None:
                    return None
                with reader:
                    manifest_store = _json_mapping(reader.json(), field_name="manifest_store")
                    validation_results_raw = reader.get_validation_results()
                    validation_results = (
                        dict(validation_results_raw) if validation_results_raw is not None else {}
                    )
                    return C2paSdkPayload(
                        package_version=module.__version__,
                        sdk_version=module.sdk_version(),
                        manifest_store=manifest_store,
                        validation_state=reader.get_validation_state(),
                        validation_results=validation_results,
                    )
        except Exception as error:
            errors = module.C2paError
            if isinstance(error, errors.ManifestNotFound):
                return None
            if isinstance(error, (errors.NotSupported, errors.RemoteManifest)):
                raise C2paUnsupportedError(error.__class__.__name__) from error
            if isinstance(
                error,
                (
                    errors.Verify,
                    errors.Signature,
                    errors.Manifest,
                    errors.Json,
                    errors.Decoding,
                ),
            ):
                raise C2paInvalidManifestError(error.__class__.__name__) from error
            if isinstance(error, C2paInvalidManifestError):
                raise
            raise C2paRuntimeError(error.__class__.__name__) from error


def _active_manifest(manifest_store: Mapping[str, object]) -> Mapping[str, object]:
    active_label = manifest_store.get("active_manifest")
    manifests = manifest_store.get("manifests")
    if not isinstance(active_label, str) or not isinstance(manifests, dict):
        return {}
    active = cast(dict[object, object], manifests).get(active_label)
    if not isinstance(active, dict):
        return {}
    active_mapping = cast(dict[object, object], active)
    if not all(isinstance(key, str) for key in active_mapping):
        return {}
    return cast(dict[str, object], active_mapping)


def _walk(value: object, *, limit: int = 20_000) -> tuple[tuple[str | None, object], ...]:
    stack: list[tuple[str | None, object]] = [(None, value)]
    observed: list[tuple[str | None, object]] = []
    while stack:
        key, item = stack.pop()
        observed.append((key, item))
        if len(observed) > limit:
            raise C2paInvalidManifestError("C2PA JSON exceeds bounded traversal limit")
        if isinstance(item, dict):
            for child_key, child in cast(dict[object, object], item).items():
                stack.append((str(child_key), child))
        elif isinstance(item, list):
            stack.extend((key, child) for child in cast(list[object], item))
    return tuple(observed)


def _status_codes(
    validation_results: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    success: set[str] = set()
    failure: set[str] = set()
    informational: set[str] = set()
    stack: list[tuple[str | None, object]] = [(None, validation_results)]
    while stack:
        category, item = stack.pop()
        if isinstance(item, dict):
            mapping = cast(dict[object, object], item)
            code = mapping.get("code")
            if isinstance(code, str):
                if category == "failure":
                    failure.add(code)
                elif category == "success":
                    success.add(code)
                else:
                    informational.add(code)
            for key, child in mapping.items():
                normalized = str(key).casefold()
                next_category = (
                    normalized
                    if normalized in {"success", "failure", "informational"}
                    else category
                )
                stack.append((next_category, child))
        elif isinstance(item, list):
            stack.extend((category, child) for child in cast(list[object], item))
    return tuple(sorted(success)), tuple(sorted(failure)), tuple(sorted(informational))


def _contains(codes: tuple[str, ...], *needles: str) -> bool:
    lowered = tuple(code.casefold() for code in codes)
    return any(needle.casefold() in code for code in lowered for needle in needles)


def _specification_version(active_manifest: Mapping[str, object]) -> str | None:
    for key, value in _walk(active_manifest):
        if key in {"specVersion", "spec_version"} and isinstance(value, str):
            return value
    return None


def _spec_compatibility(version: str | None) -> C2paSpecCompatibility:
    if version is None:
        return C2paSpecCompatibility.UNKNOWN
    parts = version.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return C2paSpecCompatibility.UNKNOWN
    if major == 2 and minor == 3:
        return C2paSpecCompatibility.PREFERRED_2_3
    if major == 2:
        return C2paSpecCompatibility.COMPATIBLE_2_X
    if major < 2:
        return C2paSpecCompatibility.LEGACY
    return C2paSpecCompatibility.FUTURE_UNSUPPORTED


def _generator_information(active_manifest: Mapping[str, object]) -> tuple[str, ...]:
    generators = active_manifest.get("claim_generator_info")
    if not isinstance(generators, list):
        legacy = active_manifest.get("claim_generator")
        return (legacy,) if isinstance(legacy, str) and legacy.strip() else ()
    result: set[str] = set()
    for item in cast(list[object], generators):
        if not isinstance(item, dict):
            continue
        mapping = cast(dict[object, object], item)
        name = mapping.get("name")
        version = mapping.get("version")
        if isinstance(name, str) and name.strip():
            result.add(f"{name}@{version}" if isinstance(version, str) and version else name)
    return tuple(sorted(result))


def _ai_assertions(active_manifest: Mapping[str, object]) -> tuple[str, ...]:
    signals: set[str] = set()
    for key, value in _walk(active_manifest):
        if not isinstance(value, str):
            continue
        normalized = value.casefold()
        if any(
            marker in normalized
            for marker in (
                "trainedalgorithmic",
                "algorithmicmedia",
                "ai-generated",
                "ai_modified",
                "ai-modified",
                "generative-ai",
            )
        ):
            signals.add(f"{key or 'value'}={value}")
    return tuple(sorted(signals))


def _result(
    *,
    asset_sha256: str,
    media_type: str,
    package_version: str | None,
    sdk_version: str | None,
    specification_version: str | None,
    validation_state: C2paValidationState,
    manifest_present: bool | None,
    signature_valid: bool | None,
    trust_list_valid: bool | None,
    timestamp_valid: bool | None,
    ingredient_chain_valid: bool | None,
    content_binding_valid: bool | None,
    generator_information: tuple[str, ...],
    ai_assertions: tuple[str, ...],
    certificate_state: CertificateState,
    tamper_detected: bool | None,
    validation_codes: tuple[str, ...],
    manifest_store_sha256: str | None,
    verified_at: datetime,
    available_at: datetime,
) -> C2paVerificationResult:
    payload = {
        "asset_sha256": asset_sha256,
        "media_type": media_type,
        "package_version": package_version,
        "sdk_version": sdk_version,
        "specification_version": specification_version,
        "validation_state": validation_state.value,
        "manifest_present": manifest_present,
        "signature_valid": signature_valid,
        "trust_list_valid": trust_list_valid,
        "timestamp_valid": timestamp_valid,
        "ingredient_chain_valid": ingredient_chain_valid,
        "content_binding_valid": content_binding_valid,
        "generator_information": list(generator_information),
        "ai_assertions": list(ai_assertions),
        "certificate_state": certificate_state.value,
        "tamper_detected": tamper_detected,
        "validation_codes": list(validation_codes),
        "manifest_store_sha256": manifest_store_sha256,
        "verified_at": str(verified_at),
        "available_at": str(available_at),
    }
    return C2paVerificationResult(
        verification_id=ArtifactId(canonical_sha256(payload)),
        asset_sha256=asset_sha256,
        media_type=media_type,
        package_version=package_version,
        sdk_version=sdk_version,
        specification_version=specification_version,
        spec_compatibility=_spec_compatibility(specification_version),
        validation_state=validation_state,
        manifest_present=manifest_present,
        signature_valid=signature_valid,
        trust_list_valid=trust_list_valid,
        timestamp_valid=timestamp_valid,
        ingredient_chain_valid=ingredient_chain_valid,
        content_binding_valid=content_binding_valid,
        generator_information=generator_information,
        ai_assertions=ai_assertions,
        certificate_state=certificate_state,
        tamper_detected=tamper_detected,
        validation_codes=validation_codes,
        manifest_store_sha256=manifest_store_sha256,
        verified_at=verified_at,
        available_at=available_at,
    )


@dataclass(frozen=True, slots=True)
class C2paVerifier:
    backend: C2paBackend = field(default_factory=C2paPythonBackend)
    clock: Clock = field(default_factory=SystemClock)

    def verify_file(
        self,
        asset_path: Path,
        *,
        available_at: datetime | None = None,
        media_type: str | None = None,
    ) -> C2paVerificationResult:
        """Verify one immutable local asset without network or OCSP fetching."""

        if not asset_path.is_file() or asset_path.is_symlink():
            raise ValueError("AQ-TRUTH-C2PA-REGULAR-NON-SYMLINK-ASSET-REQUIRED")
        verified = ensure_utc(self.clock.now())
        available = verified if available_at is None else ensure_utc(available_at)
        if verified > available:
            raise ValueError("AQ-TRUTH-C2PA-RESULT-TIME-ORDER")
        asset_hash = sha256_file(asset_path)
        detected_media_type = media_type or mimetypes.guess_type(asset_path.name)[0]
        normalized_media_type = detected_media_type or "application/octet-stream"
        try:
            sdk_payload = self.backend.verify(asset_path)
        except C2paSdkUnavailableError:
            return _result(
                asset_sha256=asset_hash,
                media_type=normalized_media_type,
                package_version=None,
                sdk_version=None,
                specification_version=None,
                validation_state=C2paValidationState.SDK_UNAVAILABLE,
                manifest_present=None,
                signature_valid=None,
                trust_list_valid=None,
                timestamp_valid=None,
                ingredient_chain_valid=None,
                content_binding_valid=None,
                generator_information=(),
                ai_assertions=(),
                certificate_state=CertificateState.UNKNOWN,
                tamper_detected=None,
                validation_codes=("AQ-TRUTH-C2PA-SDK-UNAVAILABLE",),
                manifest_store_sha256=None,
                verified_at=verified,
                available_at=available,
            )
        except C2paUnsupportedError:
            return _result(
                asset_sha256=asset_hash,
                media_type=normalized_media_type,
                package_version=None,
                sdk_version=None,
                specification_version=None,
                validation_state=C2paValidationState.UNSUPPORTED,
                manifest_present=None,
                signature_valid=None,
                trust_list_valid=None,
                timestamp_valid=None,
                ingredient_chain_valid=None,
                content_binding_valid=None,
                generator_information=(),
                ai_assertions=(),
                certificate_state=CertificateState.UNKNOWN,
                tamper_detected=None,
                validation_codes=("AQ-TRUTH-C2PA-ASSET-UNSUPPORTED",),
                manifest_store_sha256=None,
                verified_at=verified,
                available_at=available,
            )
        except C2paInvalidManifestError:
            return _result(
                asset_sha256=asset_hash,
                media_type=normalized_media_type,
                package_version=None,
                sdk_version=None,
                specification_version=None,
                validation_state=C2paValidationState.INVALID,
                manifest_present=True,
                signature_valid=None,
                trust_list_valid=None,
                timestamp_valid=None,
                ingredient_chain_valid=None,
                content_binding_valid=None,
                generator_information=(),
                ai_assertions=(),
                certificate_state=CertificateState.INVALID,
                tamper_detected=None,
                validation_codes=("AQ-TRUTH-C2PA-MANIFEST-INVALID",),
                manifest_store_sha256=None,
                verified_at=verified,
                available_at=available,
            )
        except C2paRuntimeError:
            return _result(
                asset_sha256=asset_hash,
                media_type=normalized_media_type,
                package_version=None,
                sdk_version=None,
                specification_version=None,
                validation_state=C2paValidationState.ERROR,
                manifest_present=None,
                signature_valid=None,
                trust_list_valid=None,
                timestamp_valid=None,
                ingredient_chain_valid=None,
                content_binding_valid=None,
                generator_information=(),
                ai_assertions=(),
                certificate_state=CertificateState.UNKNOWN,
                tamper_detected=None,
                validation_codes=("AQ-TRUTH-C2PA-VERIFICATION-ERROR",),
                manifest_store_sha256=None,
                verified_at=verified,
                available_at=available,
            )

        if sdk_payload is None:
            return _result(
                asset_sha256=asset_hash,
                media_type=normalized_media_type,
                package_version=None,
                sdk_version=None,
                specification_version=None,
                validation_state=C2paValidationState.ABSENT,
                manifest_present=False,
                signature_valid=None,
                trust_list_valid=None,
                timestamp_valid=None,
                ingredient_chain_valid=None,
                content_binding_valid=None,
                generator_information=(),
                ai_assertions=(),
                certificate_state=CertificateState.NOT_PRESENT,
                tamper_detected=None,
                validation_codes=("AQ-TRUTH-C2PA-MANIFEST-ABSENT",),
                manifest_store_sha256=None,
                verified_at=verified,
                available_at=available,
            )
        return self._from_sdk_payload(
            sdk_payload,
            asset_sha256=asset_hash,
            media_type=normalized_media_type,
            verified_at=verified,
            available_at=available,
        )

    @staticmethod
    def _from_sdk_payload(
        payload: C2paSdkPayload,
        *,
        asset_sha256: str,
        media_type: str,
        verified_at: datetime,
        available_at: datetime,
    ) -> C2paVerificationResult:
        active = _active_manifest(payload.manifest_store)
        success, failure, informational = _status_codes(payload.validation_results)
        codes = tuple(sorted(set(success) | set(failure) | set(informational)))
        normalized_state = (payload.validation_state or "").casefold()
        if normalized_state == "trusted" and not failure:
            state = C2paValidationState.TRUSTED
        elif normalized_state == "valid" and not failure:
            state = C2paValidationState.VALID
        else:
            state = C2paValidationState.INVALID

        signature_failed = _contains(
            failure,
            "claimsignature.mismatch",
            "claimsignature.missing",
            "signature.invalid",
        )
        binding_failed = _contains(failure, "hash", "binding")
        timestamp_failed = _contains(failure, "timestamp", "timeStamp")
        ingredient_failed = _contains(failure, "ingredient")
        timestamp_success = _contains(success, "timestamp", "timeStamp")
        ingredient_present = isinstance(active.get("ingredients"), list) and bool(
            active.get("ingredients")
        )

        signature_succeeded = _contains(success, "claimsignature.validated")
        binding_succeeded = _contains(success, "hash.match", "binding.validated")
        if state in {C2paValidationState.VALID, C2paValidationState.TRUSTED}:
            signature_valid: bool | None = True
            content_binding_valid: bool | None = True
            tamper_detected: bool | None = False
        else:
            signature_valid = False if signature_failed else True if signature_succeeded else None
            content_binding_valid = False if binding_failed else True if binding_succeeded else None
            tamper_detected = (
                True
                if signature_failed or binding_failed
                else False
                if signature_valid is True and content_binding_valid is True
                else None
            )
        trust_list_valid = (
            True
            if state is C2paValidationState.TRUSTED
            else False
            if state is C2paValidationState.VALID
            else None
        )
        timestamp_valid = False if timestamp_failed else True if timestamp_success else None
        ingredient_chain_valid = (
            False
            if ingredient_failed
            else True
            if ingredient_present
            and state in {C2paValidationState.VALID, C2paValidationState.TRUSTED}
            else None
        )
        if state is C2paValidationState.TRUSTED:
            certificate_state = CertificateState.TRUSTED
        elif state is C2paValidationState.VALID:
            certificate_state = CertificateState.VALID_UNTRUSTED
        elif _contains(failure, "expired", "outsideValidity"):
            certificate_state = CertificateState.EXPIRED
        elif _contains(failure, "revoked"):
            certificate_state = CertificateState.REVOKED
        else:
            certificate_state = CertificateState.INVALID

        specification_version = _specification_version(active)
        return _result(
            asset_sha256=asset_sha256,
            media_type=media_type,
            package_version=payload.package_version,
            sdk_version=payload.sdk_version,
            specification_version=specification_version,
            validation_state=state,
            manifest_present=True,
            signature_valid=signature_valid,
            trust_list_valid=trust_list_valid,
            timestamp_valid=timestamp_valid,
            ingredient_chain_valid=ingredient_chain_valid,
            content_binding_valid=content_binding_valid,
            generator_information=_generator_information(active),
            ai_assertions=_ai_assertions(active),
            certificate_state=certificate_state,
            tamper_detected=tamper_detected,
            validation_codes=codes,
            manifest_store_sha256=canonical_sha256(payload.manifest_store),
            verified_at=verified_at,
            available_at=available_at,
        )
