"""Shared P01 test fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def project_root() -> Path:
    """Return the repository root."""
    return Path(__file__).resolve().parents[2]
