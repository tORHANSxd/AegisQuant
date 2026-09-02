import Link from "next/link";

import { StatusBadge } from "../../../../src/components/common";
import { DataState } from "../../../../src/components/data-state";
import { getOrderTrace } from "../../../../src/lib/api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const stageNames = {
  SIGNAL: "信号",
  EVENT_EVIDENCE: "事件证据",
  MODEL: "模型",
  RISK: "独立风险",
  ORDER: "订单",
  FILL: "成交",
  LEDGER: "账本",
} as const;

function stageTone(status: "VERIFIED" | "NOT_APPLICABLE" | "NOT_AVAILABLE") {
  if (status === "VERIFIED") return "positive" as const;
  if (status === "NOT_APPLICABLE") return "neutral" as const;
  return "danger" as const;
}

export default async function OrderTracePage({
  params,
}: Readonly<{ params: Promise<{ orderId: string }> }>) {
  const { orderId } = await params;
  const trace = await getOrderTrace(orderId);
  const payload = trace.payload;

  return (
    <DataState
      state="STALE"
      asOf={trace.as_of_time}
      source={trace.source_artifact}
      authoritative={trace.authoritative}
      estimated={trace.estimated}
      lastSuccessAt={trace.projected_at}
      reason="决策链来自历史开发/Paper 工件，不是实时交易状态。"
    >
      <div className="page-stack">
        <header className="page-header">
          <div>
            <p className="eyebrow">ORDER DECISION TRACE</p>
            <h1>订单完整决策链</h1>
            <p className="lede">
              从信号到最终账本逐段展示；不适用的环节明确标记，不拿并不存在的模型或事件关联硬凑因果。
            </p>
          </div>
          <div className="freshness">
            <span>订单</span>
            <strong>{payload.order_id}</strong>
            <small>{payload.instrument_id} · {payload.strategy_id}</small>
          </div>
        </header>

        <section className="metric-grid" aria-label="决策链摘要">
          <article className="metric-card"><span>链完整性</span><strong>{payload.complete ? "COMPLETE" : "INCOMPLETE"}</strong><small>七段均有显式状态</small></article>
          <article className="metric-card"><span>决策时间</span><strong className="metric-time">{new Date(payload.decision_time).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}</strong><small>北京时间</small></article>
          <article className="metric-card"><span>账户</span><strong>{payload.account_id}</strong><small>历史开发账户</small></article>
          <article className="metric-card"><span>因果夸大</span><strong>{payload.causal_link_overclaimed ? "是" : "否"}</strong><small>schema 强制 false</small></article>
        </section>

        <section className="surface" aria-labelledby="trace-stages-title">
          <div className="surface-heading">
            <div><p className="section-kicker">SIGNAL → LEDGER</p><h2 id="trace-stages-title">七段证据链</h2></div>
            <StatusBadge label={payload.complete ? "完整" : "不完整"} tone={payload.complete ? "positive" : "danger"} />
          </div>
          <ol className="trace-stage-list">
            {payload.stages.map((stage) => (
              <li key={`${stage.sequence}:${stage.stage}`}>
                <span className="trace-sequence" aria-hidden="true">{stage.sequence}</span>
                <div className="trace-stage-heading">
                  <div><strong>{stageNames[stage.stage]}</strong><small>{stage.stage}</small></div>
                  <StatusBadge label={stage.status} tone={stageTone(stage.status)} />
                </div>
                <p>{stage.explanation}</p>
                <dl>
                  <div><dt>实体</dt><dd>{stage.entity_id ?? "不适用"}</dd></div>
                  <div><dt>证据工件</dt><dd><code>{stage.source_artifact}</code></dd></div>
                </dl>
              </li>
            ))}
          </ol>
        </section>

        <Link className="secondary-button trace-back" href="/execution">← 返回执行工作台</Link>
      </div>
    </DataState>
  );
}
