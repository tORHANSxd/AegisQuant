"""P10 global event-intelligence and deferred formal-acceptance gates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import polars as pl
import yaml


def _json(path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))


def test_p10_state_is_current_deferred_live_locked_and_p09_is_preserved(
    project_root: Path,
) -> None:
    state = cast(
        "dict[str, object]",
        yaml.safe_load(
            (project_root / "state/PROJECT_PHASE_STATE.yaml").read_text(encoding="utf-8")
        ),
    )
    previous = cast("dict[str, object]", state["previous_phase"])
    deferred = cast("list[dict[str, object]]", state["deferred_acceptance_queue"])
    assert state["current_phase"] in {
        "P10",
        "P11",
        "P12",
        "P13",
        "P14",
        "P15",
        "P16",
        "P17",
        "P18",
    }
    assert state["status"] == "in_progress"
    assert state["accepted_at_utc"] is None
    assert state["formal_acceptance_deferred"] is True
    assert state["live_trading_locked"] is True
    if state["current_phase"] == "P10":
        p09 = next(item for item in deferred if item["phase"] == "P09")
        assert state["next_phase"] == "P11"
        assert previous["phase"] == "P09"
        assert previous["evidence_commit_sha"] == p09["evidence_commit_sha"]
        required = {"P05", "P06", "P07", "P08", "P09"}
    elif state["current_phase"] == "P11":
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert state["next_phase"] == "P12"
        assert previous["phase"] == "P10"
        assert previous["evidence_commit_sha"] == p10["evidence_commit_sha"]
        required = {"P05", "P06", "P07", "P08", "P09", "P10"}
    elif state["current_phase"] == "P12":
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert state["next_phase"] == "P13"
        assert previous["phase"] == "P11"
        assert p10["status"] == "implementation_verified_acceptance_deferred"
        required = {"P05", "P06", "P07", "P08", "P09", "P10", "P11"}
    elif state["current_phase"] == "P13":
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert state["next_phase"] == "P14"
        assert previous["phase"] == "P12"
        assert p10["status"] == "implementation_verified_acceptance_deferred"
        required = {"P05", "P06", "P07", "P08", "P09", "P10", "P11", "P12"}
    elif state["current_phase"] == "P14":
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert state["next_phase"] == "P15"
        assert previous["phase"] == "P13"
        assert p10["status"] == "implementation_verified_acceptance_deferred"
        required = {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
            "P13",
        }
    elif state["current_phase"] == "P15":
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert state["next_phase"] == "P16"
        assert previous["phase"] == "P14"
        assert p10["status"] == "implementation_verified_acceptance_deferred"
        required = {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
            "P13",
            "P14",
        }
    elif state["current_phase"] == "P16":
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert state["next_phase"] == "P17"
        assert previous["phase"] == "P15"
        assert p10["status"] == "implementation_verified_acceptance_deferred"
        required = {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            "P10",
            "P11",
            "P12",
            "P13",
            "P14",
            "P15",
        }
    else:
        p10 = next(item for item in deferred if item["phase"] == "P10")
        assert previous["phase"] in {"P16", "P17"}
        assert p10["status"] == "implementation_verified_acceptance_deferred"
        current_number = int(cast("str", state["current_phase"]).removeprefix("P"))
        required = {
            "P05",
            "P06",
            "P07",
            "P08",
            "P09",
            *(f"P{number:02d}" for number in range(10, current_number)),
        }
    assert {item["phase"] for item in deferred} >= required
    assert not (project_root / "reports/phases/P10/ACCEPTANCE.md").exists()
    assert not (project_root / "src/aegisquant/live").exists()


def test_p10_traceability_has_18_verified_tasks_and_10_deferred_acceptance_rows(
    project_root: Path,
) -> None:
    with (project_root / "reports/phases/P10/REQUIREMENTS_TRACEABILITY.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 28
    assert len({row["requirement_id"] for row in rows}) == 28
    tasks = [row for row in rows if row["category"] == "task"]
    acceptance = [row for row in rows if row["category"] == "acceptance"]
    assert len(tasks) == 18 and {row["status"] for row in tasks} == {"verified"}
    assert len(acceptance) == 10 and {row["status"] for row in acceptance} == {"in_progress"}
    for row in rows:
        assert (project_root / row["implementation"]).exists(), row["requirement_id"]
        assert (project_root / row["test"]).exists(), row["requirement_id"]
        assert (project_root / row["evidence"]).exists(), row["requirement_id"]


def test_p10_source_contracts_are_vintage_reproducible_and_credentials_are_honest(
    project_root: Path,
) -> None:
    source = _json(project_root / "reports/data/P10_SOURCE_CONTRACT_EVIDENCE.json")
    social = _json(project_root / "reports/data/P10_SOCIAL_SOURCE_EVIDENCE.json")
    policy = _json(project_root / "reports/data/P10_SOURCE_POLICY_EVIDENCE.json")
    before = cast("list[dict[str, object]]", source["alfred_before_revision"])
    after = cast("list[dict[str, object]]", source["alfred_after_revision"])
    requests = cast("dict[str, dict[str, object]]", source["requests"])
    assert before[0]["value"] == "100.0" and after[0]["value"] == "101.5"
    assert source["future_revision_leakage"] is False
    assert requests["fred_alfred"]["runtime_state"] == "AWAITING_CREDENTIALS"
    assert requests["dune"]["executable"] is False
    assert source["network_requests_performed"] == 0
    assert social["bluesky_v2_checkpoint"] == "seq"
    assert social["gdelt_is_authoritative_evidence"] is False
    assert social["telegram_mtproto_or_user_session_used"] is False
    assert social["credentials_requested_or_stored"] is False
    assert policy["disabled_by_policy"] == ["reddit_disabled", "discord_disabled"]
    assert policy["foundation_model_training_allowed"] is False


def test_p10_dune_registry_and_official_catalog_are_reproducible(project_root: Path) -> None:
    query = _json(project_root / "reports/intelligence/DUNE_QUERY_REGISTRY.json")
    results = _json(project_root / "reports/intelligence/DUNE_RESULT_MANIFESTS.json")
    catalog = pl.read_parquet(project_root / "reports/intelligence/OFFICIAL_SOURCE_CATALOG.parquet")
    assert query["write_sql_allowed"] is False
    query_record = cast("dict[str, object]", query["query"])
    manifests = cast("list[dict[str, object]]", results["manifests"])
    assert len(str(query_record["sql_sha256"])) == 64
    assert manifests[0]["query_version"] == query_record["version"]
    assert manifests[0]["row_count"] == 1
    assert {
        "central_bank",
        "regulator",
        "court",
        "exchange",
        "project",
        "etf_issuer",
    } <= set(catalog["authority_type"].to_list())


def test_p10_event_graph_counts_reposts_once_and_traces_committee_provenance(
    project_root: Path,
) -> None:
    event = _json(project_root / "reports/data/P10_EVENT_GRAPH_EVIDENCE.json")
    credibility = _json(project_root / "reports/data/P10_CREDIBILITY_EVIDENCE.json")
    committee = _json(project_root / "reports/data/P10_COMMITTEE_EVIDENCE.json")
    bundle = cast("dict[str, object]", event["audit_bundle"])
    deep = cast("dict[str, object]", committee["deep"])
    deep_committee = cast("dict[str, object]", deep["committee"])
    arbiter = cast("dict[str, object]", deep_committee["arbiter"])
    assert event["raw_repost_count"] == 100
    assert event["independent_repost_family_count"] == 1
    assert bundle["policy_ids"] == ["official_web_catalog_v1"]
    assert bundle["skeptic_claim_ids"] == ["skeptic-claim"]
    assert credibility["hotness_used_as_independence"] is False
    assert credibility["reposts_used_as_independence"] is False
    assert arbiter["should_abstain"] is True
    assert committee["single_post_order_capability"] is False
    assert committee["llm_order_command_capability"] is False


def test_p10_fusion_and_same_budget_ablation_keep_positive_and_negative_results(
    project_root: Path,
) -> None:
    fusion = _json(project_root / "reports/data/P10_FUSION_EVIDENCE.json")
    ablation = _json(project_root / "reports/data/P10_ABLATION_EVIDENCE.json")
    report = cast("dict[str, object]", ablation["report"])
    scores = cast("list[dict[str, object]]", report["scores"])
    signs = {str(item["view"]): item["result_sign"] for item in scores}
    assert fusion["assets"] == ["BTC", "ETH"]
    assert len(cast("list[object]", fusion["required_features"])) == 6
    assert fusion["future_features_used"] is False
    assert fusion["order_capability"] is False
    assert ablation["same_budget"] is True
    assert ablation["winner_selected_post_hoc"] is False
    assert signs["FUSED"] == "POSITIVE"
    assert {value for value in signs.values()} >= {"POSITIVE", "NEGATIVE"}


def test_p10_replay_excludes_future_revision_engagement_and_runs_all_stress_checks(
    project_root: Path,
) -> None:
    replay = _json(project_root / "reports/data/P10_REPLAY_EVIDENCE.json")
    selection = cast("dict[str, object]", replay["selection"])
    selected_revision = cast("dict[str, object]", selection["revision"])
    latency = cast("dict[str, object]", replay["latency_stress"])
    scenarios = cast("list[dict[str, object]]", latency["scenarios"])
    negative = cast("dict[str, object]", replay["pretrend_placebo_negative_control"])
    assert replay["first_revision_preserved"] is True
    assert replay["future_revision_used"] is False
    assert replay["future_engagement_used"] is False
    assert selected_revision["revision"] == 2
    assert [item["delay_seconds"] for item in scenarios] == [5, 30, 120, 600]
    assert negative["passed"] is False


def test_p10_five_read_models_and_source_retirement_are_materialized(project_root: Path) -> None:
    read_models = _json(project_root / "reports/intelligence/P10_READ_MODELS.json")
    monitor = _json(project_root / "reports/data/P10_SOURCE_MONITOR_EVIDENCE.json")
    assert {
        "event_radar",
        "evidence_graph",
        "narrative_monitor",
        "source_monitor",
        "event_replay",
    } <= set(read_models)
    read_root = project_root / "reports/intelligence/read_models"
    assert {path.name for path in read_root.glob("*.json")} == {
        "EVENT_RADAR.json",
        "EVIDENCE_GRAPH.json",
        "NARRATIVE_MONITOR.json",
        "SOURCE_MONITOR.json",
        "EVENT_REPLAY.json",
    }
    dispositions = {
        item["disposition"] for item in cast("list[dict[str, object]]", monitor["decisions"])
    }
    assert dispositions == {"RISK_ONLY", "RETIRE"}


def test_p10_phase_reports_and_security_evidence_are_complete(project_root: Path) -> None:
    phase = project_root / "reports/phases/P10"
    required = {
        "PLAN.md",
        "SUMMARY.md",
        "TEST_RESULTS.json",
        "RISKS.md",
        "NEXT_ACTIONS.md",
        "ARTIFACT_MANIFEST.json",
        "ADR_REFERENCES.md",
        "REQUIREMENTS_TRACEABILITY.csv",
        "CI_RESULTS.json",
        "PYTHON_314_CONTRACT.json",
    }
    assert required.issubset({path.name for path in phase.iterdir() if path.is_file()})
    assert not (phase / "ACCEPTANCE.md").exists()
    mutation = _json(project_root / "reports/testing/P10_MUTATION_RESULTS.json")
    security = _json(project_root / "reports/security/SECURITY_SCAN_RESULTS.json")
    compliance = _json(project_root / "reports/licenses/COMPLIANCE_SUMMARY.json")
    mutation_score = cast("float", mutation["score"])
    mutation_threshold = cast("float", mutation["threshold"])
    assert mutation["status"] == "passed" and mutation_score >= mutation_threshold
    assert (
        security["phase"] in {"P10", "P11", "P12", "P13", "P14", "P15", "P16", "P17", "P18"}
        and security["secret_finding_count"] == 0
    )
    assert compliance["phase"] in {
        "P10",
        "P11",
        "P12",
        "P13",
        "P14",
        "P15",
        "P16",
        "P17",
        "P18",
    }
    assert compliance["python_unknown_license_count"] == 0
