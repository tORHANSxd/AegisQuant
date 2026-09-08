from decimal import Decimal

from aegisquant.research.prediction_metrics import prediction_metrics


def test_flat_is_not_counted_as_a_correct_short_prediction() -> None:
    result = prediction_metrics(
        tuple(map(Decimal, ("0", "0", "0.1"))), tuple(map(Decimal, ("-0.1", "0", "0.1")))
    )
    assert result.class_order == ("SHORT", "FLAT", "LONG")
    assert result.confusion_matrix == ((0, 1, 0), (0, 1, 0), (0, 0, 1))
    assert result.direction_accuracy == Decimal(2) / 3
    assert result.balanced_accuracy == Decimal(2) / 3
    assert result.macro_f1 == (Decimal(2) / 3 + 1) / 3
    assert result.abstention_coverage == Decimal(2) / 3
    assert result.r2_out_of_sample is None


def test_three_class_probabilities_and_past_mean_benchmark() -> None:
    values = tuple(map(Decimal, ("-0.1", "0", "0.1")))
    probabilities = (
        (Decimal("1"), Decimal("0"), Decimal("0")),
        (Decimal("0"), Decimal("1"), Decimal("0")),
        (Decimal("0"), Decimal("0"), Decimal("1")),
    )
    result = prediction_metrics(
        values, values, class_probabilities=probabilities, past_benchmark=(Decimal("0.02"),) * 3
    )
    assert result.brier_score == result.calibration_error == 0
    assert result.matthews_correlation == result.r2_out_of_sample == 1
    assert result.pearson_ic == result.spearman_ic == 1


def test_constant_predictions_cannot_produce_correlation_or_sign_significance() -> None:
    result = prediction_metrics((Decimal("0"),) * 3, tuple(map(Decimal, ("-0.1", "0", "0.1"))))
    assert result.pearson_ic is result.spearman_ic is result.sign_test_statistic is None
    assert result.matthews_correlation is None
