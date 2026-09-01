import { getOverview } from "../../src/lib/api";
import { EquityChart } from "../../src/components/charts/chart-suite";
import { DataState } from "../../src/components/data-state";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const money = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export default async function OverviewPage() {
  const data = await getOverview();
  const account = data.account.payload;
  const pnl = data.pnl.payload;
  const risk = data.risk.payload;
  const asOf = new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "Asia/Shanghai",
  }).format(new Date(data.account.as_of_time));

  return (
    <DataState
      state={data.account.quality_state === "LIVE" ? "LIVE" : "STALE"}
      asOf={data.account.as_of_time}
      source={data.account.source_artifact}
      authoritative={data.account.authoritative}
      estimated={data.account.estimated}
      lastSuccessAt={data.account.projected_at}
      reason="当前展示的是经验证的历史开发快照，不是实时账户流。"
    >
      <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">PORTFOLIO COMMAND CENTER</p>
          <h1>账户与风险总览</h1>
          <p className="lede">
            由服务端 Read Model 提供的只读历史开发快照，不代表实时行情、实盘收益或生产 Alpha。
          </p>
        </div>
        <div className="freshness" title={data.snapshot_sha256}>
          <span>数据截至</span>
          <strong>{asOf}</strong>
          <small>快照 {data.snapshot_sha256.slice(0, 12)}…</small>
        </div>
      </header>

      <section className="metric-grid" aria-label="账户核心指标">
        <article className="metric-card hero-metric">
          <span>账户权益</span>
          <strong>{money.format(Number(account.equity))}</strong>
          <small>
            {account.reporting_asset_id} · {account.source_scope}
          </small>
        </article>
        <article className="metric-card">
          <span>当日净损益</span>
          <strong className={Number(pnl.net) >= 0 ? "positive" : "negative"}>
            {money.format(Number(pnl.net))}
          </strong>
          <small>
            费用 {money.format(Number(pnl.fees))} {pnl.reporting_asset_id}
          </small>
        </article>
        <article className="metric-card">
          <span>风险状态</span>
          <strong className="state-normal">{risk.state}</strong>
          <small>{risk.reason_codes.join(" · ")}</small>
        </article>
        <article className="metric-card">
          <span>保证金利用率</span>
          <strong>{percent.format(Number(risk.margin_utilization))}</strong>
          <small>新增风险 {risk.new_risk_allowed ? "策略允许" : "已阻断"}</small>
        </article>
      </section>

      <section className="dashboard-grid">
        <article className="surface wide">
          <div className="surface-heading">
            <div>
              <p className="section-kicker">EQUITY TRACE</p>
              <h2>权益轨迹</h2>
            </div>
            <span className="quality-badge">{data.account.quality_state}</span>
          </div>
          <EquityChart
            points={account.equity_curve.map((point) => ({
              label: new Date(point.time).toLocaleTimeString("zh-CN", {
                timeZone: "Asia/Shanghai",
              }),
              value: Number(point.value),
            }))}
          />
        </article>

        <article className="surface">
          <div className="surface-heading">
            <div>
              <p className="section-kicker">RISK POSTURE</p>
              <h2>风险姿态</h2>
            </div>
          </div>
          <dl className="fact-list">
            <div>
              <dt>回撤</dt>
              <dd>{percent.format(Number(risk.drawdown_fraction))}</dd>
            </div>
            <div>
              <dt>总敞口权重</dt>
              <dd>{percent.format(Number(risk.gross_weight))}</dd>
            </div>
            <div>
              <dt>流动性分数</dt>
              <dd>{percent.format(Number(risk.liquidity_score))}</dd>
            </div>
            <div>
              <dt>账本对账</dt>
              <dd>{risk.ledger_reconciled ? "一致" : "异常"}</dd>
            </div>
          </dl>
        </article>
      </section>

      <section className="surface" aria-labelledby="positions-title">
        <div className="surface-heading">
          <div>
            <p className="section-kicker">CURRENT EXPOSURE</p>
            <h2 id="positions-title">当前持仓</h2>
          </div>
          <span>{data.positions.length} 条只读记录</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>标的</th>
                <th>策略</th>
                <th>数量</th>
                <th>标记价格</th>
                <th>未实现损益</th>
                <th>质量</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((position) => (
                <tr key={position.entity_id}>
                  <td>{position.payload.instrument_id}</td>
                  <td>{position.payload.strategy_id}</td>
                  <td>{position.payload.quantity}</td>
                  <td>{money.format(Number(position.payload.mark_price))}</td>
                  <td
                    className={
                      Number(position.payload.unrealized_pnl) >= 0 ? "positive" : "negative"
                    }
                  >
                    {money.format(Number(position.payload.unrealized_pnl))}
                  </td>
                  <td>
                    <span className="quality-badge">{position.quality_state}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      </div>
    </DataState>
  );
}
