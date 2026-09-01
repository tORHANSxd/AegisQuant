export default function IntelligenceLoading() {
  return (
    <section className="state-panel" aria-live="polite" aria-busy="true">
      <span className="loading-line" />
      <span className="loading-line short" />
      <p>正在读取事件、证据与来源政策…</p>
    </section>
  );
}
