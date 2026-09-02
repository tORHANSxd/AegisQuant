import { WorkspaceRoute, type WorkspaceRouteProps } from "../../src/components/workspace-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default function PerformancePage(props: WorkspaceRouteProps) {
  return <WorkspaceRoute page="performance" {...props} />;
}
