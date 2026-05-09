export const READ_AGENT_WORKSPACE_SEARCH_PARAM = "readAgent";
export const READ_AGENT_WORKSPACE_SEARCH_VALUE = "1";
export const READ_AGENT_NEW_CHAT_PATH = `/workspace/chats/new?${READ_AGENT_WORKSPACE_SEARCH_PARAM}=${READ_AGENT_WORKSPACE_SEARCH_VALUE}`;

export const REST_ENDPOINTS = [
  "GET /api/read-agent/health",
  "POST /api/read-agent/projects",
  "GET /api/read-agent/projects",
  "GET /api/read-agent/projects/{project_id}",
  "POST /api/read-agent/projects/{project_id}/blueprints",
  "GET /api/read-agent/projects/{project_id}/blueprints/{blueprint_id}",
  "GET /api/read-agent/projects/{project_id}/floors/{floor_id}/view-model",
  "GET /api/read-agent/projects/{project_id}/floors/{floor_id}/semantic-json",
  "POST /api/read-agent/runs",
  "GET /api/read-agent/runs/{run_id}",
  "GET /api/read-agent/runs/{run_id}/events",
  "POST /api/read-agent/editor/operations/preview",
  "POST /api/read-agent/editor/operations/commit",
  "POST /api/read-agent/editor/ocr-region",
  "POST /api/read-agent/editor/validate",
] as const;

export const SSE_EVENT_TYPES = [
  "run.started",
  "blueprint.started",
  "tool.completed",
  "stage.completed",
  "view_model.updated",
  "ready_for_edit",
  "run.failed",
  "stream.closed",
] as const;

export function getReadAgentLoginRedirectPath(): string {
  return READ_AGENT_NEW_CHAT_PATH;
}

export function buildReadAgentThreadPath(threadId: string): string {
  return `/workspace/chats/${encodeURIComponent(threadId)}?${READ_AGENT_WORKSPACE_SEARCH_PARAM}=${READ_AGENT_WORKSPACE_SEARCH_VALUE}`;
}

export function isReadAgentWorkspacePath(pathOrUrl: string): boolean {
  const parsed = new URL(pathOrUrl, "http://localhost");
  if (parsed.pathname === "/read-agent") return true;
  return (
    parsed.pathname.startsWith("/workspace/chats/") &&
    parsed.searchParams.get(READ_AGENT_WORKSPACE_SEARCH_PARAM) ===
      READ_AGENT_WORKSPACE_SEARCH_VALUE
  );
}
