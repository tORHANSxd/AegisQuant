"""R4 quantity buffer, adapted from the supplied reference without ledger side effects.

The caller retains precision, cash, fees, risk limits and pending-order management.
Input availability must cover every dependency. A target is never a booked fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum

ZERO = Decimal("0")
ONE = Decimal("1")


def _number(name: str, value: object) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} 必须是 Decimal，禁止隐式接收 float")
    if not value.is_finite() or value < ZERO:
        raise ValueError(f"{name} 必须有限且非负")


def _utc(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} 必须是明确 UTC 的 datetime")


class Action(StrEnum):
    HOLD = "HOLD"
    REQUEST_TARGET = "REQUEST_TARGET"
    RECONCILE_PENDING = "RECONCILE_PENDING"
    BLOCKED = "BLOCKED"


def _positive_interval(value: object) -> None:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ValueError("review_interval 必须是正 timedelta")


@dataclass(frozen=True)
class BufferPolicy:
    relative_half_width: Decimal = Decimal("0.10")
    review_interval: timedelta = timedelta(days=1)

    def __post_init__(self) -> None:
        _number("relative_half_width", self.relative_half_width)
        if self.relative_half_width > ONE:
            raise ValueError("缓冲半宽不得超过参考数量")
        _positive_interval(self.review_interval)


@dataclass(frozen=True)
class Snapshot:
    decision_time: datetime
    available_time: datetime
    current_quantity: Decimal
    raw_target_quantity: Decimal
    reference_quantity: Decimal
    hard_max_quantity: Decimal
    trend_active: bool
    market_executable: bool = True
    hard_exit: bool = False
    pending_order_count: int = 0
    last_regular_review: datetime | None = None
    regular_review_due_override: bool | None = None

    def __post_init__(self) -> None:
        _utc("decision_time", self.decision_time)
        _utc("available_time", self.available_time)
        if self.available_time > self.decision_time:
            raise ValueError("输入依赖尚不可用")
        for key in (
            "current_quantity",
            "raw_target_quantity",
            "reference_quantity",
            "hard_max_quantity",
        ):
            _number(key, getattr(self, key))
        for key in ("trend_active", "market_executable", "hard_exit"):
            if type(getattr(self, key)) is not bool:
                raise TypeError(f"{key} 必须是 bool")
        if type(self.pending_order_count) is not int or self.pending_order_count < 0:
            raise ValueError("pending_order_count 必须是非负整数")
        if (
            self.regular_review_due_override is not None
            and type(self.regular_review_due_override) is not bool
        ):
            raise TypeError("regular_review_due_override 必须是 bool 或 None")
        if self.last_regular_review is not None:
            _utc("last_regular_review", self.last_regular_review)
            if self.last_regular_review > self.decision_time:
                raise ValueError("上次调仓检查时间不能来自未来")
        if self.raw_target_quantity > ZERO and self.reference_quantity == ZERO:
            raise ValueError("正目标数量需要正参考数量")


@dataclass(frozen=True)
class Decision:
    action: Action
    target_quantity: Decimal | None
    reason: str
    regular_review_performed: bool = False
    lower_band: Decimal | None = None
    upper_band: Decimal | None = None


DEFAULT_BUFFER_POLICY = BufferPolicy()


def decide_buffered_target(
    snapshot: Snapshot, policy: BufferPolicy = DEFAULT_BUFFER_POLICY
) -> Decision:
    """Buffer ordinary resizes, preserving entry, trend exits and hard limits.

    Pass the original scheduler's review decision through the explicit override.
    RECONCILE_PENDING asks the existing order manager to wait, reuse or cancel as
    appropriate; it never erases intervening fills or unconditionally cancels.
    """
    s = snapshot
    if not s.market_executable:
        return Decision(Action.BLOCKED, None, "NO_EXECUTABLE_MARKET")
    if s.pending_order_count:
        return Decision(Action.RECONCILE_PENDING, None, "PENDING_ORDER_RECONCILIATION")

    def result(
        target: Decimal,
        reason: str,
        *,
        reviewed: bool = False,
        lower: Decimal | None = None,
        upper: Decimal | None = None,
    ) -> Decision:
        if target < ZERO or (target > s.hard_max_quantity and target != s.current_quantity):
            raise AssertionError("参考目标违反硬数量约束")
        action = Action.HOLD if target == s.current_quantity else Action.REQUEST_TARGET
        return Decision(action, target, reason, reviewed, lower, upper)

    if s.hard_exit:
        return result(ZERO, "HARD_EXIT")
    if not s.trend_active:
        return result(ZERO, "TREND_EXIT_OR_FLAT")
    if s.current_quantity > s.hard_max_quantity:
        return result(s.hard_max_quantity, "HARD_CAP_REDUCTION")

    target = min(s.raw_target_quantity, s.hard_max_quantity)
    if s.current_quantity == ZERO:
        return result(target, "NEW_TREND_ENTRY" if target else "ZERO_RISK_BUDGET")

    due = s.regular_review_due_override
    if due is None:
        due = (
            s.last_regular_review is None
            or s.decision_time - s.last_regular_review >= policy.review_interval
        )
    if not due:
        return result(s.current_quantity, "REGULAR_REVIEW_NOT_DUE")
    if target == ZERO:
        return result(ZERO, "SCHEDULED_ZERO_RISK_TARGET", reviewed=True)

    with localcontext() as ctx:
        ctx.prec = 50
        half_width = s.reference_quantity * policy.relative_half_width
        lower = max(ZERO, target - half_width)
        upper = min(s.hard_max_quantity, target + half_width)
        if s.current_quantity < lower:
            return result(lower, "BUFFER_RISK_RESTORE", reviewed=True, lower=lower, upper=upper)
        if s.current_quantity > upper:
            return result(upper, "BUFFER_RISK_REDUCE", reviewed=True, lower=lower, upper=upper)
        return result(s.current_quantity, "INSIDE_BUFFER", reviewed=True, lower=lower, upper=upper)
