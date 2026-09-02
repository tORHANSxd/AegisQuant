import { WorkspaceRoute, type WorkspaceRouteProps } from "../../src/components/workspace-route";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export default function OverviewPage(props: WorkspaceRouteProps) {
  return <WorkspaceRoute page="overview" {...props} />;
}
