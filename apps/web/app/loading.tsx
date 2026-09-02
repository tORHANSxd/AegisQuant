export default function RouteLoading() {
  return (
    <section className="state-panel" aria-live="polite" aria-busy="true">
      <span className="loading-line" />
      <span className="loading-line short" />
      <p>正在读取当前路由的服务端快照…</p>
    </section>
  );
}
