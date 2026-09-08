"""只对用户最新粘贴报告的数值做 Decimal 算术；不读取本地交易系统或回放。

snapshot.json 是手工结构化摘录，不是用户本地 results.json 的拷贝。
成本加回仅表示期末机械返还，不是零成本重跑结果或其一般上界。
"""
from __future__ import annotations
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent
    source = json.loads((root / 'snapshot.json').read_text(encoding='utf-8'))
    initial = Decimal(source['initial_usdt'])
    days = (datetime.fromisoformat(source['end_exclusive']) - datetime.fromisoformat(source['start'])).days
    out = {'basis': 'USER_PASTED_REPORT_ARITHMETIC_ONLY', 'elapsed_days': days,
           'not_a_new_backtest': True, 'not_a_zero_cost_replay': True, 'strategies': {}}
    for key, row in source['strategies'].items():
        final, costs = Decimal(row['final_usdt']), Decimal(row['execution_cost_usdt'])
        pnl = final - initial
        fills, cycles = Decimal(row['fills']), Decimal(row['closed_trades'])
        refund = final + costs
        out['strategies'][key] = {
            'net_pnl_usdt': str(pnl), 'net_return': str(pnl/initial),
            'fills_per_closed_cycle': str(fills/cycles),
            'cost_fraction_initial_capital': str(costs/initial),
            'cost_fraction_net_profit': str(costs/pnl),
            'terminal_cost_refund_sensitivity_usdt': str(refund),
            'terminal_cost_refund_cagr_illustration': (float(refund/initial))**(365.25/days)-1,
            'calmar_from_report_rounded_metrics': str(Decimal(row['cagr'])/Decimal(row['max_drawdown'])),
        }
    a, b = source['strategies']['A1'], source['strategies']['A3']
    cost_saved = Decimal(a['execution_cost_usdt'])-Decimal(b['execution_cost_usdt'])
    pnl_delta = Decimal(b['final_usdt'])-Decimal(a['final_usdt'])
    out['a3_minus_a1'] = {
        'net_pnl_delta_usdt': str(pnl_delta), 'execution_cost_saved_usdt': str(cost_saved),
        'pnl_plus_reported_cost_delta_usdt': str(pnl_delta-cost_saved),
        'average_exposure_ratio': str(Decimal(b['average_exposure'])/Decimal(a['average_exposure'])),
        'net_profit_ratio': str((Decimal(b['final_usdt'])-initial)/(Decimal(a['final_usdt'])-initial)),
        'not_a_causal_model_attribution': True,
    }
    out['a7_to_a1_average_exposure_ratio'] = str(Decimal(source['strategies']['A7']['average_exposure'])/Decimal(a['average_exposure']))
    out['coin_deltas_from_rounded_percentages_usdt'] = {
        coin: str(Decimal('10000')*(Decimal(rows['A3'])-Decimal(rows['A1'])))
        for coin, rows in source['coin_returns'].items()
    }
    delta_sum = sum(map(Decimal, out['coin_deltas_from_rounded_percentages_usdt'].values()))
    out['coin_delta_sum_minus_portfolio_delta_rounding_usdt'] = str(delta_sum-pnl_delta)
    (root/'derived_metrics.json').write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(out['a3_minus_a1'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
