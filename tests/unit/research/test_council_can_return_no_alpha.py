from decimal import Decimal

import pytest

from aegisquant.research.council import CouncilDecision, run_model_council
from aegisquant.research.models.baselines import ResearchModality
from tests.research.test_model_council import candidate


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({"net_return": Decimal("-0.3")}, CouncilDecision.NO_PROVEN_ALPHA),
        ({"gate_evidence_sha256": None}, CouncilDecision.INSUFFICIENT_EVIDENCE),
        ({"stability_gate_passed": False}, CouncilDecision.REJECTED_FOR_INSTABILITY),
        ({"cost_stress_gate_passed": False}, CouncilDecision.NO_PROVEN_ALPHA),
    ),
)
def test_council_abstains_and_blocks_new_positions(
    changes: dict[str, object],
    expected: CouncilDecision,
) -> None:
    tested = candidate("trend", "TREND", ResearchModality.MARKET_ONLY, "0.01").model_copy(
        update=changes
    )
    report = run_model_council(
        candidates=(tested,),
        baseline_model_id="trend",
        minimum_incremental_improvement=Decimal("0.01"),
    )
    assert report.decision is expected
    assert report.selected_model_id is None
    assert report.new_positions_allowed is False


def test_economic_increment_keeps_simple_baseline_when_complexity_does_not_pay() -> None:
    baseline = candidate("trend", "TREND", ResearchModality.MARKET_ONLY, "0.2")
    complex_model = candidate("tree", "XGBOOST", ResearchModality.MARKET_ONLY, "0.01").model_copy(
        update={"net_return": Decimal("0.105")}
    )
    report = run_model_council(
        candidates=(baseline, complex_model),
        baseline_model_id="trend",
        minimum_incremental_improvement=Decimal("0.01"),
    )
    assert report.decision is CouncilDecision.SELECTED
    assert report.selected_model_id == "trend"
