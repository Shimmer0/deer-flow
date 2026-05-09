import { afterEach, describe, expect, test, vi } from "vitest";

import { createProject } from "@/features/read-agent/api";

describe("read-agent API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(globalThis, "document");
  });

  test("sends CSRF header from cookie for mutating requests", async () => {
    Object.defineProperty(globalThis, "document", {
      configurable: true,
      value: { cookie: "csrf_token=rightplay-token" },
    });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "project-real-loop",
            name: "RealLoop",
            buildings: [],
            floors: [],
            blueprints: [],
            created_at: "2026-05-09T00:00:00Z",
            updated_at: "2026-05-09T00:00:00Z",
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    await createProject({ name: "RealLoop", building_name: "主楼" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/read-agent/projects",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({ "X-CSRF-Token": "rightplay-token" }),
        method: "POST",
      }),
    );
  });
});
