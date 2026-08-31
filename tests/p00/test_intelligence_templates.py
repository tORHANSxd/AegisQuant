"""Initial event-intelligence policy artifact tests."""

from pathlib import Path

import yaml


def test_event_ontology_is_evidence_first(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "knowledge/event_ontology/event_types.yaml").read_text(encoding="utf-8")
    )

    assert len(payload["event_types"]) >= 6
    assert all(event["direct_order_action_allowed"] is False for event in payload["event_types"])
    assert payload["invariants"]["abstain_without_evidence"] is True
    assert payload["invariants"]["social_engagement_is_point_in_time"] is True


def test_entity_registry_requires_versioned_evidence(project_root: Path) -> None:
    payload = yaml.safe_load(
        (project_root / "knowledge/templates/key_entity_registry.yaml").read_text(encoding="utf-8")
    )

    assert "source_evidence_ids" in payload["required_fields"]
    assert payload["identity_rules"]["aliases_are_time_versioned"] is True
    assert payload["identity_rules"]["unresolved_entities_are_not_auto_merged"] is True
