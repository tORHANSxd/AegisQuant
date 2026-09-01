from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest


@pytest.fixture
def exchange_fixtures(project_root: Path) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(
            (project_root / "tests/fixtures/p04/exchanges.json").read_text(encoding="utf-8")
        ),
    )


@pytest.fixture
def event_fixtures(project_root: Path) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(
            (project_root / "tests/fixtures/p04/event_sources.json").read_text(encoding="utf-8")
        ),
    )
