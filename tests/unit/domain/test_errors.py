"""Stable error-code and disposition tests."""

import pytest

from aegisquant.domain.errors import DomainError, ErrorDisposition


def test_domain_error_exposes_machine_stable_fields() -> None:
    error = DomainError("AQ-ORDER-UNKNOWN-STATE", ErrorDisposition.RECONCILE, "display text")
    assert error.code == "AQ-ORDER-UNKNOWN-STATE"
    assert error.disposition is ErrorDisposition.RECONCILE


def test_unknown_error_prefix_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid AegisQuant"):
        DomainError("OTHER-ERROR-CODE", ErrorDisposition.HALT, "bad")
