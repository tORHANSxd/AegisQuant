from __future__ import annotations

from pathlib import Path

CANONICAL_RUNBOOKS = (
    "DATA_STALE",
    "ORDER_UNKNOWN",
    "RECONCILIATION_FAILURE",
    "LEDGER_IMBALANCE",
    "VENUE_DISCONNECT",
    "MARGIN_RISK",
    "MODEL_DRIFT",
    "DATABASE_FAILURE",
    "DISK_FULL",
    "SECRET_LEAK",
    "LIVE_KILL_SWITCH",
    "RESTORE_FROM_BACKUP",
)


def test_all_canonical_runbooks_and_incident_templates_exist(project_root: Path) -> None:
    for name in CANONICAL_RUNBOOKS:
        path = project_root / f"docs/runbooks/{name}.md"
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        assert "Detection" in text
        assert "Forbidden actions" in text
        assert "Evidence" in text
        assert "recovery" in text.casefold()
    incident = (project_root / "docs/incident_templates/INCIDENT_RECORD.md").read_text(
        encoding="utf-8"
    )
    postmortem = (project_root / "docs/incident_templates/POSTMORTEM.md").read_text(
        encoding="utf-8"
    )
    for state in (
        "OPEN",
        "ACKNOWLEDGED",
        "MITIGATING",
        "MONITORING",
        "RESOLVED",
        "POSTMORTEM_REQUIRED",
        "CLOSED",
    ):
        assert state in incident
    assert "Blameless" in postmortem


def test_deployment_handbook_and_backup_policy_remain_non_live(project_root: Path) -> None:
    handbook = (project_root / "docs/deployment/PAPER_TESTNET_DEPLOYMENT.md").read_text(
        encoding="utf-8"
    )
    policy = (project_root / "infra/backup/BACKUP_POLICY.yaml").read_text(encoding="utf-8")
    units = "\n".join(
        path.read_text(encoding="utf-8") for path in (project_root / "infra/systemd").glob("*")
    )
    assert "不得创建 Live profile" in handbook
    assert "HALTED" in handbook
    assert "ciphertext_only: true" in policy
    assert "live_trading_enabled: false" in policy
    assert "LoadCredentialEncrypted" in units
    assert "database_dsn=" not in units.casefold()
    assert "backup_key=" not in units.casefold()
