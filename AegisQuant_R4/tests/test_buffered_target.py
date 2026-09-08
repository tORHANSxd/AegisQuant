"""独立合成测试，不是 AegisQuant 全仓测试或盈利回测。"""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import unittest
from buffered_target import Action, BufferPolicy, Snapshot, decide_buffered_target

NOW = datetime(2026, 9, 8, 0, tzinfo=timezone.utc)

def base(**changes):
    values = dict(decision_time=NOW, available_time=NOW,
                  current_quantity=D("10"), raw_target_quantity=D("10"),
                  reference_quantity=D("10"), hard_max_quantity=D("100"),
                  trend_active=True)
    values.update(changes)
    return Snapshot(**values)


class BufferTests(unittest.TestCase):
    def test_inside_holds(self):
        r = decide_buffered_target(base(current_quantity=D("10.5")))
        self.assertEqual(r.action, Action.HOLD)
        self.assertEqual(r.target_quantity, D("10.5"))
    def test_at_lower_holds(self):
        self.assertEqual(decide_buffered_target(base(current_quantity=D("9"))).action, Action.HOLD)
    def test_at_upper_holds(self):
        self.assertEqual(decide_buffered_target(base(current_quantity=D("11"))).action, Action.HOLD)
    def test_reduce_to_near_boundary_not_center(self):
        r = decide_buffered_target(base(current_quantity=D("13")))
        self.assertEqual(r.target_quantity, D("11"))
        self.assertEqual(r.reason, "BUFFER_RISK_REDUCE")
    def test_restore_to_near_boundary_not_center(self):
        r = decide_buffered_target(base(current_quantity=D("7")))
        self.assertEqual(r.target_quantity, D("9"))
        self.assertEqual(r.reason, "BUFFER_RISK_RESTORE")
    def test_zero_buffer_reaches_target(self):
        r = decide_buffered_target(base(current_quantity=D("7")), BufferPolicy(D("0")))
        self.assertEqual(r.target_quantity, D("10"))
    def test_not_due_holds(self):
        r = decide_buffered_target(base(current_quantity=D("7"), last_regular_review=NOW))
        self.assertEqual(r.action, Action.HOLD)
        self.assertFalse(r.regular_review_performed)
    def test_explicit_original_schedule_takes_precedence(self):
        r = decide_buffered_target(base(current_quantity=D("7"), last_regular_review=NOW, regular_review_due_override=True))
        self.assertEqual(r.target_quantity, D("9"))
    def test_explicit_original_schedule_can_defer(self):
        r = decide_buffered_target(base(current_quantity=D("7"), regular_review_due_override=False))
        self.assertEqual(r.action, Action.HOLD)
    def test_schedule_override_must_be_boolean(self):
        with self.assertRaises(TypeError): base(regular_review_due_override=1)
    def test_due_after_full_interval(self):
        r = decide_buffered_target(base(current_quantity=D("7"), last_regular_review=NOW-timedelta(days=1)))
        self.assertEqual(r.target_quantity, D("9"))
        self.assertTrue(r.regular_review_performed)
    def test_new_entry_bypasses_daily_review(self):
        r = decide_buffered_target(base(current_quantity=D("0"), last_regular_review=NOW))
        self.assertEqual(r.target_quantity, D("10"))
        self.assertFalse(r.regular_review_performed)
    def test_trend_exit_bypasses_daily_review(self):
        self.assertEqual(decide_buffered_target(base(trend_active=False, last_regular_review=NOW)).target_quantity, D("0"))
    def test_hard_exit_bypasses_buffer(self):
        self.assertEqual(decide_buffered_target(base(hard_exit=True, last_regular_review=NOW)).target_quantity, D("0"))
    def test_hard_cap_bypasses_daily_review(self):
        r = decide_buffered_target(base(hard_max_quantity=D("8"), last_regular_review=NOW))
        self.assertEqual(r.target_quantity, D("8"))
        self.assertEqual(r.reason, "HARD_CAP_REDUCTION")
    def test_band_cannot_exceed_hard_cap(self):
        r = decide_buffered_target(base(current_quantity=D("7"), hard_max_quantity=D("10.3")))
        self.assertEqual(r.upper_band, D("10.3"))
    def test_target_clips_to_cap_for_entry(self):
        r = decide_buffered_target(base(current_quantity=D("0"), hard_max_quantity=D("8")))
        self.assertEqual(r.target_quantity, D("8"))
    def test_zero_cap_requests_exit(self):
        self.assertEqual(decide_buffered_target(base(hard_max_quantity=D("0"))).target_quantity, D("0"))
    def test_pending_prevents_duplicate_order(self):
        r = decide_buffered_target(base(pending_order_count=1))
        self.assertEqual(r.action, Action.RECONCILE_PENDING)
        self.assertIsNone(r.target_quantity)
    def test_pending_hard_exit_requires_reconciliation(self):
        r = decide_buffered_target(base(pending_order_count=1, hard_exit=True))
        self.assertEqual(r.action, Action.RECONCILE_PENDING)
    def test_unexecutable_market_does_not_fake_exit(self):
        r = decide_buffered_target(base(market_executable=False, hard_exit=True))
        self.assertEqual(r.action, Action.BLOCKED)
        self.assertIsNone(r.target_quantity)
    def test_scheduled_zero_soft_target_exits(self):
        r = decide_buffered_target(base(raw_target_quantity=D("0")))
        self.assertEqual(r.target_quantity, D("0"))
    def test_unscheduled_zero_soft_target_is_not_hard_exit(self):
        r = decide_buffered_target(base(raw_target_quantity=D("0"), last_regular_review=NOW))
        self.assertEqual(r.action, Action.HOLD)
    def test_future_input_rejected(self):
        with self.assertRaises(ValueError): base(available_time=NOW+timedelta(seconds=1))
    def test_future_review_rejected(self):
        with self.assertRaises(ValueError): base(last_regular_review=NOW+timedelta(seconds=1))
    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError): base(decision_time=NOW.replace(tzinfo=None))
    def test_non_utc_rejected(self):
        with self.assertRaises(ValueError): base(decision_time=NOW.astimezone(timezone(timedelta(hours=9))))
    def test_float_rejected(self):
        with self.assertRaises(TypeError): base(current_quantity=10.0)
    def test_nan_rejected(self):
        with self.assertRaises(ValueError): base(reference_quantity=D("NaN"))
    def test_infinite_rejected(self):
        with self.assertRaises(ValueError): base(hard_max_quantity=D("Infinity"))
    def test_negative_quantity_rejected(self):
        with self.assertRaises(ValueError): base(current_quantity=D("-1"))
    def test_zero_reference_with_positive_target_rejected(self):
        with self.assertRaises(ValueError): base(reference_quantity=D("0"))
    def test_invalid_pending_count_rejected(self):
        with self.assertRaises(ValueError): base(pending_order_count=True)
    def test_non_boolean_state_rejected(self):
        with self.assertRaises(TypeError): base(trend_active=1)
    def test_negative_buffer_rejected(self):
        with self.assertRaises(ValueError): BufferPolicy(D("-0.1"))
    def test_excessive_buffer_rejected(self):
        with self.assertRaises(ValueError): BufferPolicy(D("1.1"))
    def test_zero_review_interval_rejected(self):
        with self.assertRaises(ValueError): BufferPolicy(review_interval=timedelta(0))
    def test_unit_scaling_invariance(self):
        original = base(current_quantity=D("7"))
        scaled = replace(original, current_quantity=D("7000"), raw_target_quantity=D("10000"),
                         reference_quantity=D("10000"), hard_max_quantity=D("100000"))
        self.assertEqual(decide_buffered_target(scaled).target_quantity,
                         decide_buffered_target(original).target_quantity*1000)
    def test_oscillation_demo_is_only_synthetic(self):
        targets = list(map(D, ["9.8", "10.2", "9.9", "10.1", "10"]))
        totals = []
        for width in (D("0"), D("0.10")):
            current, turnover = D("10"), D("0")
            for target in targets:
                result = decide_buffered_target(base(current_quantity=current, raw_target_quantity=target), BufferPolicy(width))
                self.assertIsNotNone(result.target_quantity)
                turnover += abs(result.target_quantity-current)
                current = result.target_quantity
            totals.append(turnover)
        self.assertGreater(totals[0], D("0"))
        self.assertEqual(totals[1], D("0"))
    def test_all_outputs_finite_nonnegative_and_bounded(self):
        for held in ("0", "0.5", "7", "10", "15", "110"):
            for target in ("0", "1", "10", "120"):
                r = decide_buffered_target(base(current_quantity=D(held), raw_target_quantity=D(target)))
                self.assertTrue(r.target_quantity.is_finite())
                self.assertGreaterEqual(r.target_quantity, D("0"))
                self.assertLessEqual(r.target_quantity, D("100"))

if __name__ == "__main__": unittest.main()
