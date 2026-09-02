import { getWorkbench } from "../lib/api";
import {
  resolveWorkspaceFilters,
  WorkspacePage,
  type WorkspacePageKey,
} from "./workspace-page";

export interface WorkspaceRouteProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function WorkspaceRoute({
  page,
  searchParams,
}: Readonly<WorkspaceRouteProps & { page: WorkspacePageKey }>) {
  const [data, values] = await Promise.all([getWorkbench(), searchParams]);
  return <WorkspacePage page={page} data={data} filters={resolveWorkspaceFilters(values)} />;
}
