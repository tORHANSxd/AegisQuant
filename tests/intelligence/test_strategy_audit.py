from __future__ import annotations

from pathlib import Path

from aegisquant.intelligence.static_analysis.audit import audit_strategy
from aegisquant.intelligence.static_analysis.extraction import extract_strategy_ir
from aegisquant.intelligence.static_analysis.models import AuditTag, RightsStatus
from aegisquant.intelligence.static_analysis.scanner import scan_source_bytes
from tests.intelligence.helpers import artifact_for, extract_fixture


def test_audit_flags_point_in_time_universe_and_restricted_rights(project_root: Path) -> None:
    path = project_root / "tests/fixtures/p09/joinquant_manual_export/code/strategy.py"
    result = extract_fixture(path)
    artifact = artifact_for(path)
    scan = scan_source_bytes(source_id=artifact.source_id, artifact=artifact, raw=path.read_bytes())
    audit = audit_strategy(
        strategy_ir=result.strategy_ir,
        scan=scan,
        evidence_spans=result.evidence_spans,
        rights_status=RightsStatus.PERSONAL_RESEARCH_ONLY,
    )
    assert AuditTag.SURVIVORSHIP_BIAS in audit.tags
    assert AuditTag.LICENSE_RESTRICTED in audit.tags
    assert AuditTag.PARTIAL in audit.tags
    assert audit.execution_allowed is False


def test_negative_shift_is_rejected_as_lookahead(tmp_path: Path) -> None:
    path = tmp_path / "lookahead.py"
    path.write_text(
        "def signal(frame):\n    future = frame.shift(-1)\n    return future > 0\n",
        encoding="utf-8",
    )
    artifact = artifact_for(path)
    raw = path.read_bytes()
    scan = scan_source_bytes(source_id=artifact.source_id, artifact=artifact, raw=raw)
    extracted = extract_strategy_ir(
        strategy_id="lookahead-strategy",
        source_id=artifact.source_id,
        artifact=artifact,
        raw=raw,
        scan=scan,
    )
    audit = audit_strategy(
        strategy_ir=extracted.strategy_ir,
        scan=scan,
        evidence_spans=extracted.evidence_spans,
        rights_status=RightsStatus.PUBLIC_LICENSE,
    )
    assert AuditTag.LEAKAGE in audit.tags
    assert AuditTag.REJECTED in audit.tags
