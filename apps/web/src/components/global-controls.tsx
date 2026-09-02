"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

const LAYOUT_KEY = "aegisquant-safe-layout-v1";
const allowedPages = [
  ["/overview", "账户与风险总览"],
  ["/live", "实时台"],
  ["/performance", "绩效"],
  ["/execution", "执行与订单追溯"],
  ["/strategies", "策略"],
  ["/models", "模型"],
  ["/market", "市场"],
  ["/intelligence", "事件情报"],
  ["/risk", "风险"],
  ["/research", "研究"],
  ["/research/intelligence", "知识情报"],
  ["/data", "数据"],
  ["/incidents", "事故"],
  ["/system", "系统"],
  ["/settings", "设置"],
] as const;

const safeQueryKeys = new Set(["range", "timezone", "account", "strategy", "venue", "currency"]);

function safeSavedTarget(value: string): string | null {
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object") return null;
    const item = parsed as { pathname?: unknown; query?: unknown };
    if (typeof item.pathname !== "string" || !allowedPages.some(([path]) => path === item.pathname)) {
      return null;
    }
    const query = new URLSearchParams(typeof item.query === "string" ? item.query : "");
    for (const key of [...query.keys()]) {
      if (!safeQueryKeys.has(key)) query.delete(key);
    }
    return query.size ? `${item.pathname}?${query.toString()}` : item.pathname;
  } catch {
    return null;
  }
}

export function GlobalControls() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [message, setMessage] = useState("");
  const controls = useRef<HTMLElement>(null);

  useEffect(() => {
    controls.current?.setAttribute("data-ready", "true");
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      }
      if (event.key === "Escape") setPaletteOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const commands = useMemo(() => {
    const query = commandQuery.trim().toLocaleLowerCase("zh-CN");
    return query
      ? allowedPages.filter(([, label]) => label.toLocaleLowerCase("zh-CN").includes(query))
      : allowedPages;
  }, [commandQuery]);

  const updateFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    next.set(key, value);
    router.replace(`${pathname}?${next.toString()}`);
  };

  const saveLayout = () => {
    window.localStorage.setItem(
      LAYOUT_KEY,
      JSON.stringify({ pathname, query: searchParams.toString(), savedAt: new Date().toISOString() }),
    );
    setMessage("当前页面与安全筛选已保存在本机。\n");
  };

  const restoreLayout = () => {
    const saved = window.localStorage.getItem(LAYOUT_KEY);
    const target = saved ? safeSavedTarget(saved) : null;
    if (!target) {
      setMessage("没有可恢复的安全布局。\n");
      return;
    }
    router.push(target);
    setMessage("已恢复本机布局。\n");
  };

  const exportView = () => {
    const content = document.querySelector("main")?.textContent?.trim() ?? "";
    const blob = new Blob([`${content}\n`], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `aegisquant-${pathname.replaceAll("/", "-").replace(/^-/, "") || "view"}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
    setMessage("当前只读视图已导出为文本。\n");
  };

  return (
    <section ref={controls} className="global-controls" aria-label="全局工作台控制">
      <form className="global-filter" onSubmit={(event) => event.preventDefault()}>
        <label>账户
          <select value={searchParams.get("account") ?? "paper-account"} onChange={(event) => updateFilter("account", event.target.value)}>
            <option value="paper-account">paper-account</option>
          </select>
        </label>
        <label>时间范围
          <select value={searchParams.get("range") ?? "ALL"} onChange={(event) => updateFilter("range", event.target.value)}>
            <option value="1D">1 日</option><option value="7D">7 日</option><option value="30D">30 日</option><option value="ALL">全部证据</option>
          </select>
        </label>
        <label>时区
          <select value={searchParams.get("timezone") ?? "Asia/Shanghai"} onChange={(event) => updateFilter("timezone", event.target.value)}>
            <option value="Asia/Shanghai">北京时间</option><option value="UTC">UTC</option>
          </select>
        </label>
        <label>策略
          <select value={searchParams.get("strategy") ?? "all"} onChange={(event) => updateFilter("strategy", event.target.value)}>
            <option value="all">全部策略</option><option value="p06-buy-hold">p06-buy-hold</option><option value="strategy-core">strategy-core</option>
          </select>
        </label>
        <label>场所
          <select value={searchParams.get("venue") ?? "all"} onChange={(event) => updateFilter("venue", event.target.value)}>
            <option value="all">全部场所</option><option value="SIM">SIM</option><option value="BINANCE-TESTNET">BINANCE-TESTNET</option>
          </select>
        </label>
        <label>计价
          <select value={searchParams.get("currency") ?? "USDT"} onChange={(event) => updateFilter("currency", event.target.value)}>
            <option value="USDT">USDT</option>
          </select>
        </label>
      </form>
      <div className="global-actions">
        <button type="button" onClick={() => setPaletteOpen(true)} aria-keyshortcuts="Control+K">命令 <kbd>Ctrl K</kbd></button>
        <button type="button" onClick={exportView}>导出</button>
        <button type="button" onClick={saveLayout}>保存布局</button>
        <button type="button" onClick={restoreLayout}>恢复布局</button>
      </div>
      <span className="sr-only" aria-live="polite">{message}</span>
      {paletteOpen ? (
        <div className="palette-backdrop" role="presentation" onMouseDown={() => setPaletteOpen(false)}>
          <section className="global-palette" role="dialog" aria-modal="true" aria-labelledby="palette-title" onMouseDown={(event) => event.stopPropagation()}>
            <div><strong id="palette-title">只读命令面板</strong><button type="button" onClick={() => setPaletteOpen(false)} aria-label="关闭命令面板">×</button></div>
            <label htmlFor="global-command-search">搜索页面</label>
            <input id="global-command-search" autoFocus type="search" value={commandQuery} onChange={(event) => setCommandQuery(event.target.value)} />
            <nav aria-label="命令结果">
              {commands.map(([href, label]) => <Link key={href} href={href} onClick={() => setPaletteOpen(false)}>{label}<small>{href}</small></Link>)}
            </nav>
          </section>
        </div>
      ) : null}
    </section>
  );
}
