"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import { GlobalControls } from "./global-controls";
import { PreferenceControls } from "./preferences";
import { RealtimeStatus } from "./realtime-status";

const navigation = [
  { group: "监控", items: [
    { href: "/overview", label: "总览" },
    { href: "/live", label: "实时台" },
    { href: "/performance", label: "绩效" },
    { href: "/risk", label: "风险" },
  ] },
  { group: "交易与市场", items: [
    { href: "/execution", label: "执行" },
    { href: "/strategies", label: "策略" },
    { href: "/models", label: "模型" },
    { href: "/market", label: "市场" },
    { href: "/intelligence", label: "事件情报" },
  ] },
  { group: "研究与运营", items: [
    { href: "/research", label: "研究" },
    { href: "/research/intelligence", label: "知识情报" },
    { href: "/data", label: "数据" },
    { href: "/incidents", label: "事故" },
    { href: "/system", label: "系统" },
    { href: "/settings", label: "设置" },
  ] },
] as const;

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  return (
    <div className="workbench">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="sidebar" aria-label="应用侧栏">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            AQ
          </span>
          <span>
            <strong>AegisQuant</strong>
            <small>Event Intelligence</small>
          </span>
        </div>
        <nav aria-label="主导航">
          {navigation.map((section) => (
            <section className="nav-group" key={section.group} aria-label={section.group}>
              <strong>{section.group}</strong>
              {section.items.map((item) => {
                const active = item.href === "/overview"
                  ? pathname === item.href
                  : pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={active ? "nav-link active" : "nav-link"}
                    href={item.href}
                    key={item.href}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </section>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span>权限</span>
          <strong>VIEWER · READ ONLY</strong>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <span className="environment-dot" aria-hidden="true" />
            RESEARCH ENVIRONMENT
          </div>
          <div className="topbar-status" aria-label="安全状态">
            <RealtimeStatus />
            <span className="status-chip warning">历史开发快照</span>
            <span className="status-chip locked">LIVE TRADING LOCKED</span>
            <PreferenceControls />
          </div>
        </header>
        <Suspense fallback={<div className="global-controls global-controls-loading" aria-busy="true">正在载入安全筛选…</div>}>
          <GlobalControls />
        </Suspense>
        <main id="main-content" className="content">
          {children}
        </main>
      </div>
    </div>
  );
}
