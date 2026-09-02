import Link from "next/link";

import { EmptyState } from "../src/components/data-state";

export default function NotFoundPage() {
  return (
    <div className="page-stack">
      <EmptyState title="没有这条只读记录" detail="目标不存在或未进入当前不可变快照。" />
      <Link className="secondary-button trace-back" href="/overview">返回总览</Link>
    </div>
  );
}
