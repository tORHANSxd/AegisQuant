LOOKBACK = 20
MAX_EXPOSURE = 0.25
FEE_BPS = 2
SLIPPAGE_BPS = 3


def initialize(context):
    set_benchmark("000300.XSHG")
    set_order_cost(OrderCost(open_commission=0.0002, close_commission=0.0002))
    set_slippage(FixedSlippage(0.0003))
    run_daily(rebalance, time="14:50")


def rebalance(context):
    universe = get_index_stocks("000300.XSHG", date=context.current_dt.date())
    prices = attribute_history(universe[0], LOOKBACK, "1d", ["close"])
    mean_price = prices["close"].mean()
    latest_price = prices["close"].iat[LOOKBACK - 1]
    if latest_price > mean_price:
        order_target_value(universe[0], context.portfolio.total_value * MAX_EXPOSURE)
    else:
        order_target_value(universe[0], 0)
