import { SettingsPanel } from "../../src/components/preferences";

export default function SettingsPage() {
  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">SAFE LOCAL PREFERENCES</p>
          <h1>安全设置</h1>
          <p className="lede">
            这里只能调整本机显示。没有账户连接、凭证输入、交易开关、风险限额或策略热更新。
          </p>
        </div>
        <div className="freshness">
          <span>权限边界</span>
          <strong>VIEWER · LOCAL ONLY</strong>
          <small>LIVE_TRADING_LOCKED=true</small>
        </div>
      </header>
      <SettingsPanel />
      <section className="surface" aria-labelledby="settings-boundary-title">
        <div className="surface-heading">
          <div><p className="section-kicker">IMMUTABLE BOUNDARY</p><h2 id="settings-boundary-title">不可从网页改变的配置</h2></div>
          <span className="status-badge tone-positive">安全锁生效</span>
        </div>
        <dl className="fact-list">
          <div><dt>真实交易账户</dt><dd>未连接</dd></div>
          <div><dt>API Secret / Cookie / 验证码</dt><dd>不接收、不保存</dd></div>
          <div><dt>LIVE_TRADING</dt><dd>LOCKED</dd></div>
          <div><dt>风险限额</dt><dd>只读签名策略</dd></div>
          <div><dt>策略与模型发布</dt><dd>无网页入口</dd></div>
        </dl>
      </section>
    </div>
  );
}
