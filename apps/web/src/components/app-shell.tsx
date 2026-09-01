"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { PreferenceControls } from "./preferences";
import { RealtimeStatus } from "./realtime-status";

const navigation = [
  { href: "/overview", label: "总览" },
  { href: "/intelligence", label: "事件情报" },
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
          {navigation.map((item) => {
            const active = pathname.startsWith(item.href);
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
        <main id="main-content" className="content">
          {children}
        </main>
      </div>
    </div>
  );
}
