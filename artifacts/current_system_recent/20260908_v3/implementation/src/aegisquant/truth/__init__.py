"""Truth-verification package for source identity, provenance, and later phases."""

from aegisquant.truth.c2pa import C2paVerifier
from aegisquant.truth.identity import assess_official_identity, verify_detached_signature
from aegisquant.truth.manipulation import SourceCompromiseStore
from aegisquant.truth.provenance import (
    ContentIntegrityStore,
    assess_content_integrity,
    bind_content_authenticity,
)
from aegisquant.truth.source_registry import SourceRegistry

__all__ = [
    "C2paVerifier",
    "ContentIntegrityStore",
    "SourceCompromiseStore",
    "SourceRegistry",
    "assess_content_integrity",
    "assess_official_identity",
    "bind_content_authenticity",
    "verify_detached_signature",
]
