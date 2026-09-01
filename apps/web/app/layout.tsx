import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "../src/components/app-shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "AegisQuant — Read-only Intelligence",
  description: "AegisQuant v3.1 local read-only market intelligence workbench",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
