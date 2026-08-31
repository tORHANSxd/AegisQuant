export const runtime = "nodejs";

const locks = [
  "真实订单提交已禁用",
  "实盘适配器注册表为空",
  "账户秘密加载已禁用",
] as const;

export default function HomePage() {
  return (
    <main className="shell">
      <section className="panel" aria-labelledby="title">
        <p className="eyebrow">AEGISQUANT · PHASE P00</p>
        <h1 id="title">工程安全基线</h1>
        <div className="status-row" aria-label="运行状态">
          <span className="badge development">DEVELOPMENT</span>
          <span className="badge locked">LIVE LOCKED</span>
        </div>
        <p className="summary">
          当前界面只呈现只读启动状态。这里没有账户连接、交易控件或解锁入口。
        </p>
        <ul>
          {locks.map((lock) => (
            <li key={lock}>{lock}</li>
          ))}
        </ul>
      </section>
    </main>
  );
}
