import { expect, test } from "vitest";

import {
  ACCEPTANCE_MATRIX,
  REST_ENDPOINTS,
  SSE_EVENT_TYPES,
  commitOperationPreview,
  createInitialReadAgentState,
  createOperationPreview,
  getBlueprintsForFloor,
  getSchematic3dNotice,
  redoNextOperation,
  requestOcrCandidate,
  undoLastCommittedOperation,
} from "@/features/read-agent/model";

test("maps supplement acceptance criteria to implemented UI surfaces", () => {
  expect(ACCEPTANCE_MATRIX.map((item) => item.docSection)).toEqual([
    "13.1 Processing Mode",
    "13.2 Edit Mode",
    "13.3 原图对比和证据",
    "13.4 多楼层/三维",
    "13.5 审计",
  ]);

  expect(
    ACCEPTANCE_MATRIX.every(
      (item) => item.implementedBy.length > 0 && item.testedBy.length > 0,
    ),
  ).toBe(true);
});

test("keeps documented SSE event types and REST endpoints deployable in the UI", () => {
  expect(SSE_EVENT_TYPES).toEqual([
    "agent.status",
    "agent.tool_call",
    "agent.tool_result",
    "artifact.created",
    "recognition.updated",
    "view_model.updated",
    "validation.updated",
    "uncertainty.updated",
    "ready_for_edit",
  ]);

  expect(REST_ENDPOINTS).toContain("GET /api/projects/{project_id}");
  expect(REST_ENDPOINTS).toContain("POST /api/editor/operations/preview");
  expect(REST_ENDPOINTS).toContain("POST /api/editor/operations/commit");
});

test("creates preview operation, JSON Patch, commit delta, audit, undo and redo", () => {
  const initial = createInitialReadAgentState();
  const preview = createOperationPreview(initial, {
    objectId: "beam-B3",
    updates: {
      label: "KL3(2A)",
      section: "300x700",
      reviewStatus: "accepted",
    },
    actor: "tester",
  });

  expect(preview.validation.ok).toBe(true);
  expect(preview.operation.type).toBe("update_beam");
  expect(preview.jsonPatch).toEqual([
    { op: "replace", path: "/objects/beam-B3/label", value: "KL3(2A)" },
    { op: "replace", path: "/objects/beam-B3/section", value: "300x700" },
    {
      op: "replace",
      path: "/objects/beam-B3/review_status",
      value: "accepted",
    },
  ]);
  expect(initial.objects["beam-B3"]?.label).toBe("KL3(2)");

  const committed = commitOperationPreview(initial, preview);
  expect(committed.objects["beam-B3"]?.label).toBe("KL3(2A)");
  expect(committed.auditLog).toHaveLength(1);
  expect(committed.auditLog[0]?.actor).toBe("tester");

  const undone = undoLastCommittedOperation(committed);
  expect(undone.objects["beam-B3"]?.label).toBe("KL3(2)");

  const redone = redoNextOperation(undone);
  expect(redone.objects["beam-B3"]?.label).toBe("KL3(2A)");
});

test("rejects invalid editor operations before commit", () => {
  const state = createInitialReadAgentState();
  const preview = createOperationPreview(state, {
    objectId: "beam-B3",
    updates: { section: "bad-section" },
    actor: "tester",
  });

  expect(preview.validation.ok).toBe(false);
  expect(preview.validation.issues).toContain(
    "梁截面必须使用宽x高格式，例如 300x700。",
  );
  expect(() => commitOperationPreview(state, preview)).toThrow(
    "Validation failed",
  );
});

test("supports floor blueprint switching, schematic 3D warning, and OCR candidates", () => {
  const state = createInitialReadAgentState();

  expect(getBlueprintsForFloor(state.project, "F03")).toEqual([
    "PL-S-001",
    "PL-S-001-R2",
  ]);
  expect(getBlueprintsForFloor(state.project, "F02")).toEqual(["PL-S-002"]);
  expect(getSchematic3dNotice(state.project, "F03")).toBe(
    "示意模型，不可用于工程计算",
  );
  expect(getSchematic3dNotice(state.project, "F02")).toBeNull();

  const ocr = requestOcrCandidate("beam-B3", {
    x: 31100,
    y: 19100,
    width: 900,
    height: 420,
  });
  expect(ocr.autoCommit).toBe(false);
  expect(ocr.candidates[0]?.text).toBe("KL3(2)");
});
