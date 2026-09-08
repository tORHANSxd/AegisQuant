#!/usr/bin/env python3
"""AegisQuant 静态公式的独立数值复核；不导入仓库、不训练、不回测。

根据 2026-09-08 已读取的源码公式建立最小算例，所有市场/概率输入均为
人为指定的说明性输入，不是从用户交易记录计算的真实分布。
运行：python AegisQuant_formula_probes.py --output AegisQuant_formula_probes.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any

getcontext().prec = 40
D = Decimal


def probes() -> dict[str, Any]:
    # 源码标签：第 i+1 根开盘入场，第 i+h 根开盘退出。
    holding_hours = {str(h): (h - 1) * 4 for h in (6, 12)}
    assert holding_hours == {"6": 20, "12": 44}

    # 当前经济门槛的说明性成本输入，不是实际交易成本估计。
    natr, notional, quote_volume = D("0.01"), D("10000"), D("100000000")
    fee, half_spread = D("0.001"), D("0.0001")
    slippage = D("0.0002") + D("0.01") * natr
    impact = D("0.0025") * min(D(1), notional / quote_volume)
    entry = fee + half_spread + slippage + impact + D("0.0001")
    exit_cost = fee + half_spread + slippage + impact
    round_trip = entry + exit_cost
    hurdle = D(2) * round_trip + D("0.0002")
    assert round_trip == D("0.00290050")
    assert hurdle == D("0.00600100")

    # economic_gate 入场权重；cat_replay 随后乘 0.99。
    sizing: list[dict[str, str]] = []
    for p in (D("0.56"), D("0.60"), D("0.70")):
        vol_cap = min(D(1), D("0.20") / D("0.80"))
        confidence = min(D(1), max(D(0), (p - D("0.55")) / D("0.15")))
        sizing.append({
            "p_net_positive": str(p), "annualized_volatility": "0.80",
            "volatility_cap_weight": str(vol_cap), "confidence_multiplier": str(confidence),
            "gate_target_weight": str(vol_cap * confidence),
            "replay_target_weight_after_0_99": str(vol_cap * confidence * D("0.99")),
        })
    assert D(sizing[0]["replay_target_weight_after_0_99"]) == D("0.0165")
    assert abs(D(sizing[1]["replay_target_weight_after_0_99"]) - D("0.0825")) < D("1e-35")

    # 已持仓分支的最小例子：无退出、无风控否决，仅检查只减不加逻辑。
    current, cap = D("0.03"), D("0.25")
    held_action = "REDUCE" if cap < current else "HOLD"
    assert held_action == "HOLD"

    # 常数原始预测 + 验证集平均残差 = 验证集标签均值。
    point = D("0.002")
    truth = [D("-0.01"), D("0"), D("0.004"), D("0.008")]
    mean_truth = sum(truth) / D(len(truth))
    mean_bias = sum(y - point for y in truth) / D(len(truth))
    calibrated = point + mean_bias
    assert calibrated == mean_truth == D("0.0005")

    return {
        "status": "FORMULA_ONLY_NOT_PROJECT_EXECUTION",
        "audit_date": "2026-09-08",
        "scope": "独立数值算例；不是源码导入测试、仓库测试、模型拟合、交易归因或完整回测。",
        "label_actual_holding_hours_at_4h_bars": holding_hours,
        "label_semantics_note": "是否错误取决于 horizon 的业务定义；应先固定合同，不能直接当作 off-by-one 修复。",
        "illustrative_cost_gate": {
            "inputs": {"natr": str(natr), "order_notional_usdt": str(notional), "quote_volume_usdt": str(quote_volume)},
            "entry_bps": str(entry * 10000), "exit_bps": str(exit_cost * 10000),
            "round_trip_bps": str(round_trip * 10000),
            "entry_hurdle_bps_before_other_filters": str(hurdle * 10000),
            "note": "忽略额外模型不确定性及持有成本；只是所示公式和输入的结果，不是报告中平均门槛。",
        },
        "illustrative_B7_entry_weights": sizing,
        "illustrative_held_branch": {"current_weight": str(current), "new_volatility_cap": str(cap), "action": held_action},
        "constant_prediction_calibration_identity": {
            "raw_constant": str(point), "validation_mean": str(mean_truth),
            "mean_residual": str(mean_bias), "corrected_prediction": str(calibrated),
            "note": "此恒等式不证明真实 Elastic Net 的系数为零或预测为常数。",
        },
        "full_feature_warmup_240_bars_days": 240 * 4 / 24,
        "report_B5_vs_B3_closed_trade_count_increase": str((D(152) / D(104) - 1) * 100),
        "potential_new_period_days_2025_10_01_to_2026_09_08": (date(2026, 9, 8) - date(2025, 10, 1)).days,
        "new_period_note": "未确认这段时期是否真正从未被访问；不能自动称为盲测。",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("AegisQuant_formula_probes.json"))
    parser.add_argument("--report", type=Path, help="可选：仅计算报告 SHA-256，不读取其他研究数据。")
    args = parser.parse_args()
    result = probes()
    if args.report is not None:
        if not args.report.is_file():
            parser.error(f"报告不存在：{args.report}")
        result["report_sha256"] = hashlib.sha256(args.report.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
