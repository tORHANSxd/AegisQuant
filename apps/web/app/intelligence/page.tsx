import { AttributionWaterfall } from "../../src/components/charts/chart-suite";
import { DataState } from "../../src/components/data-state";
import { getIntelligenceOverview } from "../../src/lib/api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const percentage = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 1,
});

export default async function IntelligencePage() {
  const data = await getIntelligenceOverview();
  const event = data.events[0];
  const earliest = [...data.events].sort(
    (left, right) => Date.parse(left.as_of_time) - Date.parse(right.as_of_time),
  )[0];
  const state = data.events.some((item) => item.quality_state === "ERROR")
    ? "DEGRADED"
    : data.events.every((item) => item.quality_state === "LIVE")
      ? "LIVE"
      : "STALE";

  return (
    <DataState
      state={state}
      asOf={earliest?.as_of_time}
      source={event?.source_artifact ?? "reports/intelligence/read_models"}
      authoritative={false}
      estimated
      lastSuccessAt={event?.projected_at}
      reason="事件影响来自历史夹具与估算模型，不能直接生成订单。"
    >
      <div className="page-stack">
        <header className="page-header">
          <div>
            <p className="eyebrow">MULTIMODAL EVENT INTELLIGENCE</p>
            <h1>全球事件与叙事情报</h1>
            <p className="lede">
              事件、证据、叙事和来源政策来自同一只读快照；所有影响值均标记为非权威估算。
            </p>
          </div>
          <div className="freshness" title={data.snapshot_sha256}>
            <span>证据快照</span>
            <strong>{data.events.length} 个事件 · {data.claims.length} 条证据</strong>
            <small>{data.snapshot_sha256.slice(0, 12)}…</small>
          </div>
        </header>

        <section className="surface" aria-labelledby="event-radar-title">
          <div className="surface-heading">
            <div>
              <p className="section-kicker">EVENT RADAR</p>
              <h2 id="event-radar-title">事件雷达</h2>
            </div>
            <span>不构成交易建议</span>
          </div>
          <div className="event-grid">
            {data.events.map((item) => (
              <article className="event-card" key={item.entity_id}>
                <div>
                  <span className={`status-badge tone-${item.payload.risk_action === "HALT" ? "danger" : "warning"}`}>
                    {item.payload.risk_action}
                  </span>
                  <span className="quality-badge">{item.payload.status}</span>
                </div>
                <h3>{item.payload.event_cluster_id}</h3>
                <p>{item.payload.affected_assets.join(" · ")} · {item.payload.independent_family_count} 个独立来源家族</p>
                <dl className="impact-strip">
                  <div><dt>5m</dt><dd>{percentage.format(Number(item.payload.impact_5m))}</dd></div>
                  <div><dt>30m</dt><dd>{percentage.format(Number(item.payload.impact_30m))}</dd></div>
                  <div><dt>4h</dt><dd>{percentage.format(Number(item.payload.impact_4h))}</dd></div>
                  <div><dt>1d</dt><dd>{percentage.format(Number(item.payload.impact_1d))}</dd></div>
                  <div><dt>7d</dt><dd>{percentage.format(Number(item.payload.impact_7d))}</dd></div>
                </dl>
                <footer>
                  置信度 {percentage.format(Number(item.payload.confidence))} ·
                  {item.payload.price_led_event ? " 价格先行" : " 事件先行"} · 估算
                </footer>
              </article>
            ))}
          </div>
        </section>

        {event ? (
          <section className="dashboard-grid intelligence-detail">
            <article className="surface">
              <div className="surface-heading">
                <div><p className="section-kicker">IMPACT HORIZONS</p><h2>多时域影响</h2></div>
              </div>
              <AttributionWaterfall
                points={[
                  { label: "5m", value: Number(event.payload.impact_5m) },
                  { label: "30m", value: Number(event.payload.impact_30m) },
                  { label: "4h", value: Number(event.payload.impact_4h) },
                  { label: "1d", value: Number(event.payload.impact_1d) },
                  { label: "7d", value: Number(event.payload.impact_7d) },
                ]}
              />
            </article>
            <article className="surface" aria-labelledby="evidence-title">
              <div className="surface-heading">
                <div><p className="section-kicker">EVIDENCE GRAPH</p><h2 id="evidence-title">证据关系</h2></div>
              </div>
              <ol className="evidence-list">
                {data.claims.map((claim) => (
                  <li key={claim.entity_id}>
                    <span className={`relation relation-${claim.payload.relation.toLowerCase()}`}>{claim.payload.relation}</span>
                    <div><strong>{claim.payload.claim_id}</strong><small>{claim.payload.source_family_id} · {claim.payload.model_version}</small></div>
                    <span>{claim.payload.lawful_excerpt_available ? "可显示合法摘录" : "全文受限，仅显示证据 ID"}</span>
                  </li>
                ))}
              </ol>
            </article>
          </section>
        ) : null}

        <section className="dashboard-grid">
          <article className="surface" aria-labelledby="narrative-title">
            <div className="surface-heading"><div><p className="section-kicker">NARRATIVE MONITOR</p><h2 id="narrative-title">叙事监控</h2></div></div>
            <div className="narrative-list">
              {data.narratives.map((narrative) => (
                <article key={narrative.entity_id}>
                  <strong>{narrative.payload.topic}</strong>
                  <span>{narrative.payload.propagation_stage}</span>
                  <small>{narrative.payload.independent_author_count} 位独立作者 · 协调风险 {percentage.format(Number(narrative.payload.coordination_risk))}</small>
                  <small>速度与 attention half-life：来源未提供，未补造</small>
                </article>
              ))}
            </div>
          </article>
          <article className="surface" aria-labelledby="source-title">
            <div className="surface-heading"><div><p className="section-kicker">SOURCE MONITOR</p><h2 id="source-title">来源与政策</h2></div></div>
            <div className="source-list">
              {data.sources.map((source) => (
                <article key={source.entity_id}>
                  <div><strong>{source.payload.source_id}</strong><span className="quality-badge">{source.payload.policy_status}</span></div>
                  <p>{source.payload.runtime_state} · {source.payload.disposition}</p>
                  <small>{source.payload.reason_codes.join(" · ")} · 缺口 {source.payload.gap_count}</small>
                </article>
              ))}
            </div>
          </article>
        </section>
      </div>
    </DataState>
  );
}
