import { describe, expect, test } from "vitest";

import {
  READ_AGENT_NEW_CHAT_PATH,
  READ_AGENT_WORKSPACE_SEARCH_PARAM,
  READ_AGENT_WORKSPACE_SEARCH_VALUE,
  REST_ENDPOINTS,
  SSE_EVENT_TYPES,
  buildReadAgentThreadPath,
  getReadAgentLoginRedirectPath,
  isReadAgentWorkspacePath,
} from "@/features/read-agent/model";

describe("read-agent real-loop model contract", () => {
  test("exposes only real read-agent REST endpoints", () => {
    expect(REST_ENDPOINTS).toEqual([
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
    ]);
  });

  test("tracks real-loop SSE event types", () => {
    expect(SSE_EVENT_TYPES).toEqual([
      "run.started",
      "blueprint.started",
      "tool.completed",
      "stage.completed",
      "view_model.updated",
      "ready_for_edit",
      "run.failed",
      "stream.closed",
    ]);
  });

  test("routes login and chat shell into read-agent workspace mode", () => {
    expect(READ_AGENT_WORKSPACE_SEARCH_PARAM).toBe("readAgent");
    expect(READ_AGENT_WORKSPACE_SEARCH_VALUE).toBe("1");
    expect(READ_AGENT_NEW_CHAT_PATH).toBe("/workspace/chats/new?readAgent=1");
    expect(getReadAgentLoginRedirectPath()).toBe(READ_AGENT_NEW_CHAT_PATH);
    expect(buildReadAgentThreadPath("thread-123")).toBe(
      "/workspace/chats/thread-123?readAgent=1",
    );
  });

  test("detects read-agent workspace paths without demo identifiers", () => {
    expect(isReadAgentWorkspacePath("/read-agent")).toBe(true);
    expect(
      isReadAgentWorkspacePath("/workspace/chats/thread-123?readAgent=1"),
    ).toBe(true);
    expect(isReadAgentWorkspacePath("/workspace/chats/thread-123")).toBe(false);
    expect(
      [
        ...REST_ENDPOINTS,
        ...SSE_EVENT_TYPES,
        READ_AGENT_NEW_CHAT_PATH,
        buildReadAgentThreadPath("thread-123"),
      ].join("\n"),
    ).not.toMatch(
      /project_demo|example_project|PL-S-001_F03|packaged PL-S-001/,
    );
  });
});
