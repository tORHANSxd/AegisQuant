"""P00 architecture decision inventory tests."""

from pathlib import Path


def test_required_p00_decisions_are_accepted(project_root: Path) -> None:
    adr_paths = sorted((project_root / "docs/adr").glob("ADR-*.md"))

    assert [path.name for path in adr_paths] == [
        "ADR-0001-runtime-and-version-policy.md",
        "ADR-0002-event-engine-selection.md",
        "ADR-0003-live-lock.md",
    ]
    for path in adr_paths:
        content = path.read_text(encoding="utf-8")
        assert "状态：Accepted" in content
        assert "P00" in content
