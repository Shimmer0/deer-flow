export const SSE_EVENT_TYPES = [
  "agent.status",
  "agent.tool_call",
  "agent.tool_result",
  "artifact.created",
  "recognition.updated",
  "view_model.updated",
  "validation.updated",
  "uncertainty.updated",
  "ready_for_edit",
] as const;

export const REST_ENDPOINTS = [
  "GET /api/projects",
  "GET /api/projects/{project_id}",
  "GET /api/projects/{project_id}/blueprints/{blueprint_id}",
  "GET /api/projects/{project_id}/floors/{floor_id}/view-model",
  "POST /api/agent/runs",
  "GET /api/agent/runs/{run_id}/events",
  "POST /api/editor/operations/preview",
  "POST /api/editor/operations/commit",
  "POST /api/editor/ocr-region",
  "POST /api/editor/validate",
] as const;

export const WEB_UI_STATES = [
  "BLUEPRINT_SELECTED",
  "PROCESSING_MODE_ACTIVE",
  "STAGE_JSON_UPDATING",
  "VIEW_MODEL_DELTA_RENDERING",
  "VALIDATION_RUNNING",
  "READY_FOR_EDIT",
  "EDIT_MODE_ACTIVE",
  "OPERATION_DRAFTING",
  "OPERATION_PREVIEW",
  "OPERATION_VALIDATION",
  "OPERATION_COMMIT",
  "VIEW_MODEL_RECOMPILE",
  "FLOOR_SWITCHING",
] as const;

export const ACCEPTANCE_MATRIX = [
  {
    docSection: "13.1 Processing Mode",
    requirement:
      "加载项目、蓝图、楼层，展示 Agent 事件流、工具调用、产物、公开决策、Stage JSON 和 ViewModel JSON。",
    implementedBy: [
      "ReadAgentWorkbench project header",
      "LeftAgentPanel",
      "JsonLivePanel",
      "SSE_EVENT_TYPES",
    ],
    testedBy: ["model.test.ts SSE contract"],
  },
  {
    docSection: "13.2 Edit Mode",
    requirement:
      "基准版本锁定后进入编辑；选择梁/柱/轴网/标签；修改梁号、截面、review_status；生成 Operation、JSON Patch、Audit；校验失败不可提交；支持撤销/重做。",
    implementedBy: [
      "SemanticCanvas2D",
      "InspectorEvidencePanel",
      "createOperationPreview",
      "commitOperationPreview",
      "undoLastCommittedOperation",
      "redoNextOperation",
    ],
    testedBy: ["model.test.ts operation lifecycle"],
  },
  {
    docSection: "13.3 原图对比和证据",
    requirement:
      "正式主梁显示 evidence_ref；低置信度字段提示；OCR 框选生成候选，不自动覆盖。",
    implementedBy: [
      "EvidenceCropPanel",
      "requestOcrCandidate",
      "SemanticCanvas2D evidence bbox",
    ],
    testedBy: ["model.test.ts OCR candidate"],
  },
  {
    docSection: "13.4 多楼层/三维",
    requirement:
      "支持 floor_id 切换，一层多蓝图；三维从语义 JSON 派生且不反向编辑；缺失标高显示示意模型警告。",
    implementedBy: [
      "FloorSwitcher",
      "getBlueprintsForFloor",
      "ThreeDPreviewPanel",
      "getSchematic3dNotice",
    ],
    testedBy: ["model.test.ts floor and 3D notice"],
  },
  {
    docSection: "13.5 审计",
    requirement:
      "操作可追溯 actor、时间、对象、前值、后值、patch、校验结果；Agent trace 只展示 public trace。",
    implementedBy: ["AuditLogPanel", "publicTraceEvents", "AuditEvent"],
    testedBy: ["model.test.ts commit audit"],
  },
] as const;

export type ReviewStatus = "candidate" | "needs_review" | "accepted" | "rejected";
export type WorkbenchMode = "processing" | "edit";

export type BBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type EvidenceRef = {
  id: string;
  blueprintId: string;
  imagePath: string;
  bbox: BBox;
  confidence: number;
  source: string;
};

type SemanticObjectBase = {
  id: string;
  type: "beam" | "column" | "axis" | "label";
  label: string;
  floorId: string;
  blueprintId: string;
  reviewStatus: ReviewStatus;
  confidence: number;
  evidenceRef?: EvidenceRef;
};

export type BeamObject = SemanticObjectBase & {
  type: "beam";
  section: string;
  lineMm: [[number, number], [number, number]];
  span: string;
};

export type ColumnObject = SemanticObjectBase & {
  type: "column";
  section: string;
  coordMm: [number, number];
};

export type AxisObject = SemanticObjectBase & {
  type: "axis";
  axis: "x" | "y";
  coordMm: number;
};

export type LabelObject = SemanticObjectBase & {
  type: "label";
  text: string;
  coordMm: [number, number];
  boundObjectId: string;
};

export type SemanticObject =
  | BeamObject
  | ColumnObject
  | AxisObject
  | LabelObject;

export type Blueprint = {
  id: string;
  title: string;
  drawingType: string;
  revision: string;
};

export type Floor = {
  id: string;
  name: string;
  elevationM: number | null;
  floorHeightM: number;
  blueprints: Blueprint[];
};

export type Project = {
  id: string;
  name: string;
  discipline: string;
  buildingName: string;
  floors: Floor[];
};

export type PublicTraceEvent = {
  seq: number;
  ts: string;
  sseType: (typeof SSE_EVENT_TYPES)[number];
  stage: string;
  title: string;
  summary: string;
  publicRationale: string;
  artifacts?: string[];
};

export type StageJson = {
  stage: string;
  version: string;
  recognized: {
    grids: number;
    columns: number;
    mainBeams: number;
    labels: number;
    evidenceRefs: number;
  };
  validation: {
    status: "valid" | "warning" | "invalid";
    issues: string[];
  };
};

export type ViewModelJson = {
  schema_version: string;
  project_id: string;
  blueprint_id: string;
  floor_id: string;
  objects: Array<{
    id: string;
    type: SemanticObject["type"];
    label: string;
    review_status: ReviewStatus;
    evidence_ref?: string;
  }>;
};

export type JsonPatchOperation = {
  op: "replace";
  path: string;
  value: string;
};

export type EditorOperation = {
  id: string;
  type: "update_beam";
  project_id: string;
  blueprint_id: string;
  floor_id: string;
  base_json_version: string;
  object_id: string;
  actor: string;
  updates: Partial<{
    label: string;
    section: string;
    reviewStatus: ReviewStatus;
  }>;
};

export type ValidationResult = {
  ok: boolean;
  issues: string[];
};

export type AuditEvent = {
  id: string;
  actor: string;
  ts: string;
  objectId: string;
  before: SemanticObject;
  after: SemanticObject;
  patch: JsonPatchOperation[];
  validation: ValidationResult;
};

type HistoryEntry = {
  objectId: string;
  before: SemanticObject;
  after: SemanticObject;
  auditEvent: AuditEvent;
};

export type OperationPreview = {
  previewResultId: string;
  operation: EditorOperation;
  jsonPatch: JsonPatchOperation[];
  validation: ValidationResult;
  before?: SemanticObject;
  after?: SemanticObject;
  auditEvent?: AuditEvent;
  updatedViewModelDelta?: {
    objectId: string;
    changedPaths: string[];
  };
};

export type OcrCandidate = {
  objectId: string;
  region: BBox;
  candidates: Array<{
    text: string;
    confidence: number;
    source: string;
  }>;
  autoCommit: false;
};

export type ReadAgentState = {
  project: Project;
  selectedFloorId: string;
  selectedBlueprintId: string;
  mode: WorkbenchMode;
  baseVersionLocked: boolean;
  baseJsonVersion: string;
  editBaseVersion: string;
  objects: Record<string, SemanticObject>;
  publicTraceEvents: PublicTraceEvent[];
  stageJson: StageJson;
  viewModelJson: ViewModelJson;
  auditLog: AuditEvent[];
  undoStack: HistoryEntry[];
  redoStack: HistoryEntry[];
  ocrCandidates: OcrCandidate[];
};

const project: Project = {
  id: "project_demo_PL_S_001",
  name: "PL-S-001 示例项目",
  discipline: "结构",
  buildingName: "示例建筑",
  floors: [
    {
      id: "F03",
      name: "三层",
      elevationM: null,
      floorHeightM: 3.9,
      blueprints: [
        {
          id: "PL-S-001",
          title: "三层梁平法施工图",
          drawingType: "梁配筋/梁平面图",
          revision: "R1",
        },
        {
          id: "PL-S-001-R2",
          title: "三层梁平法施工图-复核版",
          drawingType: "梁配筋/梁平面图",
          revision: "R2",
        },
      ],
    },
    {
      id: "F02",
      name: "二层",
      elevationM: 4.2,
      floorHeightM: 3.9,
      blueprints: [
        {
          id: "PL-S-002",
          title: "二层梁平法施工图",
          drawingType: "梁配筋/梁平面图",
          revision: "R1",
        },
      ],
    },
    {
      id: "RF",
      name: "屋面",
      elevationM: 12,
      floorHeightM: 3.3,
      blueprints: [
        {
          id: "PL-S-003",
          title: "屋面梁平法施工图",
          drawingType: "梁配筋/梁平面图",
          revision: "R1",
        },
      ],
    },
  ],
};

const objects: Record<string, SemanticObject> = {
  "axis-X4": {
    id: "axis-X4",
    type: "axis",
    label: "4",
    floorId: "F03",
    blueprintId: "PL-S-001",
    reviewStatus: "accepted",
    confidence: 0.99,
    axis: "x",
    coordMm: 25200,
  },
  "axis-YD": {
    id: "axis-YD",
    type: "axis",
    label: "D",
    floorId: "F03",
    blueprintId: "PL-S-001",
    reviewStatus: "accepted",
    confidence: 0.98,
    axis: "y",
    coordMm: 22500,
  },
  "col-4D": {
    id: "col-4D",
    type: "column",
    label: "KZ-4D",
    floorId: "F03",
    blueprintId: "PL-S-001",
    reviewStatus: "accepted",
    confidence: 0.97,
    section: "500x500",
    coordMm: [25200, 22500],
    evidenceRef: {
      id: "ev-col-4D",
      blueprintId: "PL-S-001",
      imagePath: "highres_axis_enhanced_quadrants/PL-S-001_4-D__7-A.png",
      bbox: { x: 24980, y: 22260, width: 520, height: 520 },
      confidence: 0.97,
      source: "stage2_columns",
    },
  },
  "beam-B3": {
    id: "beam-B3",
    type: "beam",
    label: "KL3(2)",
    floorId: "F03",
    blueprintId: "PL-S-001",
    reviewStatus: "needs_review",
    confidence: 0.86,
    section: "300x650",
    lineMm: [
      [25200, 22500],
      [42000, 22500],
    ],
    span: "4-D to 6-D",
    evidenceRef: {
      id: "ev-beam-B3",
      blueprintId: "PL-S-001",
      imagePath: "highres_axis_enhanced_quadrants/PL-S-001_4-D__7-A.png",
      bbox: { x: 31100, y: 19100, width: 900, height: 420 },
      confidence: 0.86,
      source: "stage2_main_beams",
    },
  },
  "beam-B7": {
    id: "beam-B7",
    type: "beam",
    label: "L7?",
    floorId: "F03",
    blueprintId: "PL-S-001-R2",
    reviewStatus: "candidate",
    confidence: 0.61,
    section: "250x500",
    lineMm: [
      [7200, 9600],
      [25200, 9600],
    ],
    span: "2-B to 4-B",
    evidenceRef: {
      id: "ev-beam-B7",
      blueprintId: "PL-S-001-R2",
      imagePath: "highres_axis_enhanced_quadrants/PL-S-001_1-F__4-C.png",
      bbox: { x: 15600, y: 9000, width: 760, height: 360 },
      confidence: 0.61,
      source: "stage3_secondary_beams",
    },
  },
  "label-beam-B3": {
    id: "label-beam-B3",
    type: "label",
    label: "KL3(2)",
    floorId: "F03",
    blueprintId: "PL-S-001",
    reviewStatus: "needs_review",
    confidence: 0.86,
    text: "KL3(2) 300x650",
    coordMm: [33400, 21950],
    boundObjectId: "beam-B3",
    evidenceRef: {
      id: "ev-label-B3",
      blueprintId: "PL-S-001",
      imagePath: "highres_axis_enhanced_quadrants/PL-S-001_4-D__7-A.png",
      bbox: { x: 33020, y: 21620, width: 780, height: 320 },
      confidence: 0.86,
      source: "ocr_label_reader",
    },
  },
};

export const publicTraceEvents: PublicTraceEvent[] = [
  {
    seq: 1,
    ts: "2026-05-08T09:00:00Z",
    sseType: "agent.status",
    stage: "PROJECT_LOAD",
    title: "载入用户上传蓝图",
    summary: "PL-S-001 原图、项目、楼层元数据已入队。",
    publicRationale:
      "先用压缩全图做全局版面判断，再切换到高分辨率切片复核局部文字与轴号。",
    artifacts: ["blueprints/project_demo/original/PL-S-001.png"],
  },
  {
    seq: 2,
    ts: "2026-05-08T09:00:06Z",
    sseType: "agent.tool_call",
    stage: "STAGE1_LAYOUT",
    title: "layout_region_detector",
    summary: "检测 main_plan_region、notes_region、detail_region_candidates。",
    publicRationale:
      "结构平面图主图位于页面上方，底部为说明和详图索引，先分区再识别。",
  },
  {
    seq: 3,
    ts: "2026-05-08T09:00:16Z",
    sseType: "artifact.created",
    stage: "STAGE1_LAYOUT",
    title: "生成高清轴网切片",
    summary: "产物 stage1_layout_crops/PL-S-001/main_plan_quadrants/*.png。",
    publicRationale: "梁号和轴距需要高清轴网增强四分图。",
    artifacts: ["stage1_layout_crops/PL-S-001/main_plan_quadrants/*.png"],
  },
  {
    seq: 4,
    ts: "2026-05-08T09:00:33Z",
    sseType: "recognition.updated",
    stage: "STAGE2_GRID",
    title: "识别 X/Y 轴网尺寸链",
    summary: "X: 7200+9000+9000+7200+7200+9600=49200; Y: 41700。",
    publicRationale: "四分图补齐边缘轴号后，能复核完整尺寸链。",
  },
  {
    seq: 5,
    ts: "2026-05-08T09:00:48Z",
    sseType: "view_model.updated",
    stage: "STAGE2_COLUMNS",
    title: "生成 7x6 主轴交点柱网",
    summary: "42 个柱网候选，平均置信度 0.98。",
    publicRationale: "柱符号位于轴网交点，柱截面等待跨图纸补全。",
  },
  {
    seq: 6,
    ts: "2026-05-08T09:01:10Z",
    sseType: "uncertainty.updated",
    stage: "STAGE2_MAIN_BEAMS",
    title: "主梁 B3 需要复核",
    summary: "梁号 KL3(2) 置信度 0.86，截面 300x650 置信度 0.82。",
    publicRationale: "梁号文字与局部标注重叠，进入编辑前保留 evidence_ref。",
  },
  {
    seq: 7,
    ts: "2026-05-08T09:01:35Z",
    sseType: "validation.updated",
    stage: "VALIDATION",
    title: "语义校验通过，含 2 个提示",
    summary: "轴网闭合、主梁端点绑定通过；三层 elevation_m 缺失。",
    publicRationale: "缺失楼层标高不会阻止二维编辑，但三维必须显示示意警告。",
  },
  {
    seq: 8,
    ts: "2026-05-08T09:01:42Z",
    sseType: "ready_for_edit",
    stage: "READY_FOR_EDIT",
    title: "锁定 edit_base_version",
    summary: "edit_base_version = svm-20260508-090142。",
    publicRationale: "基准版本已锁定，编辑必须走 Operation Preview 和 Validation。",
  },
];

const stageJson: StageJson = {
  stage: "READY_FOR_EDIT",
  version: "stage3-20260508-090142",
  recognized: {
    grids: 13,
    columns: 42,
    mainBeams: 18,
    labels: 31,
    evidenceRefs: 22,
  },
  validation: {
    status: "warning",
    issues: ["F03 elevation_m 缺失，三维仅可作为示意模型。"],
  },
};

function buildViewModelJson(
  stateProject: Project,
  selectedBlueprintId: string,
  selectedFloorId: string,
  stateObjects: Record<string, SemanticObject>,
): ViewModelJson {
  return {
    schema_version: "cv-notfunning/web-semantic-view-model/v1.1",
    project_id: stateProject.id,
    blueprint_id: selectedBlueprintId,
    floor_id: selectedFloorId,
    objects: Object.values(stateObjects)
      .filter((object) => object.floorId === selectedFloorId)
      .map((object) => ({
        id: object.id,
        type: object.type,
        label: object.label,
        review_status: object.reviewStatus,
        evidence_ref: object.evidenceRef?.id,
      })),
  };
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function createInitialReadAgentState(): ReadAgentState {
  const selectedFloorId = "F03";
  const selectedBlueprintId = "PL-S-001";
  const stateObjects = clone(objects);
  const stateProject = clone(project);

  return {
    project: stateProject,
    selectedFloorId,
    selectedBlueprintId,
    mode: "processing",
    baseVersionLocked: true,
    baseJsonVersion: "stage3-20260508-090142",
    editBaseVersion: "svm-20260508-090142",
    objects: stateObjects,
    publicTraceEvents: clone(publicTraceEvents),
    stageJson: clone(stageJson),
    viewModelJson: buildViewModelJson(
      stateProject,
      selectedBlueprintId,
      selectedFloorId,
      stateObjects,
    ),
    auditLog: [],
    undoStack: [],
    redoStack: [],
    ocrCandidates: [],
  };
}

export function getBlueprintsForFloor(stateProject: Project, floorId: string) {
  return (
    stateProject.floors
      .find((floor) => floor.id === floorId)
      ?.blueprints.map((blueprint) => blueprint.id) ?? []
  );
}

export function getSchematic3dNotice(
  stateProject: Project,
  floorId: string,
): string | null {
  const floor = stateProject.floors.find((item) => item.id === floorId);
  if (floor?.elevationM !== null) return null;
  return "示意模型，不可用于工程计算";
}

function nowIso() {
  return new Date().toISOString();
}

function operationId(state: ReadAgentState, objectId: string) {
  return `op-${state.auditLog.length + 1}-${objectId}`;
}

function patchPathForUpdate(key: keyof EditorOperation["updates"]) {
  if (key === "reviewStatus") return "review_status";
  return key;
}

function applyUpdates(
  object: SemanticObject,
  updates: EditorOperation["updates"],
): SemanticObject {
  if (object.type !== "beam") return clone(object);
  return {
    ...clone(object),
    ...(updates.label !== undefined ? { label: updates.label } : {}),
    ...(updates.section !== undefined ? { section: updates.section } : {}),
    ...(updates.reviewStatus !== undefined
      ? { reviewStatus: updates.reviewStatus }
      : {}),
  };
}

function buildJsonPatch(
  object: SemanticObject,
  updates: EditorOperation["updates"],
): JsonPatchOperation[] {
  return (Object.keys(updates) as Array<keyof EditorOperation["updates"]>)
    .filter((key) => updates[key] !== undefined)
    .filter((key) => {
      if (key === "reviewStatus") return object.reviewStatus !== updates[key];
      return object.type === "beam" && object[key] !== updates[key];
    })
    .map((key) => ({
      op: "replace",
      path: `/objects/${object.id}/${patchPathForUpdate(key)}`,
      value: updates[key] ?? "",
    }));
}

function validateOperation(
  state: ReadAgentState,
  object: SemanticObject | undefined,
  updates: EditorOperation["updates"],
): ValidationResult {
  const issues: string[] = [];
  if (!state.baseVersionLocked) {
    issues.push("edit_base_version 未锁定，不能进入 Edit Mode。");
  }
  if (!object) {
    issues.push("对象不存在。");
    return { ok: false, issues };
  }
  if (object.type !== "beam") {
    issues.push("当前 MVP 只允许编辑主梁对象。");
  }
  if (updates.section !== undefined && !/^\d{2,4}x\d{2,4}$/.test(updates.section)) {
    issues.push("梁截面必须使用宽x高格式，例如 300x700。");
  }
  if (updates.label?.trim().length === 0) {
    issues.push("梁号不能为空。");
  }
  if (updates.reviewStatus === "accepted" && !object.evidenceRef) {
    issues.push("没有 evidence_ref 的对象不能写入 accepted。");
  }
  if (Object.keys(updates).length === 0) {
    issues.push("没有可预览的变更。");
  }
  return { ok: issues.length === 0, issues };
}

export function createOperationPreview(
  state: ReadAgentState,
  input: {
    objectId: string;
    updates: EditorOperation["updates"];
    actor: string;
  },
): OperationPreview {
  const object = state.objects[input.objectId];
  const validation = validateOperation(state, object, input.updates);
  const operation: EditorOperation = {
    id: operationId(state, input.objectId),
    type: "update_beam",
    project_id: state.project.id,
    blueprint_id: state.selectedBlueprintId,
    floor_id: state.selectedFloorId,
    base_json_version: state.editBaseVersion,
    object_id: input.objectId,
    actor: input.actor,
    updates: clone(input.updates),
  };

  if (!object) {
    return {
      previewResultId: `${operation.id}-preview`,
      operation,
      jsonPatch: [],
      validation,
    };
  }

  const after = applyUpdates(object, input.updates);
  const jsonPatch = buildJsonPatch(object, input.updates);
  const auditEvent: AuditEvent = {
    id: `${operation.id}-audit`,
    actor: input.actor,
    ts: nowIso(),
    objectId: object.id,
    before: clone(object),
    after: clone(after),
    patch: clone(jsonPatch),
    validation: clone(validation),
  };

  return {
    previewResultId: `${operation.id}-preview`,
    operation,
    jsonPatch,
    validation,
    before: clone(object),
    after,
    auditEvent,
    updatedViewModelDelta: {
      objectId: object.id,
      changedPaths: jsonPatch.map((patch) => patch.path),
    },
  };
}

export function commitOperationPreview(
  state: ReadAgentState,
  preview: OperationPreview,
): ReadAgentState {
  if (!preview.validation.ok || !preview.after || !preview.before || !preview.auditEvent) {
    throw new Error("Validation failed");
  }

  const nextObjects = {
    ...clone(state.objects),
    [preview.operation.object_id]: clone(preview.after),
  };
  const nextState: ReadAgentState = {
    ...clone(state),
    mode: "edit",
    objects: nextObjects,
    viewModelJson: buildViewModelJson(
      state.project,
      state.selectedBlueprintId,
      state.selectedFloorId,
      nextObjects,
    ),
    auditLog: [...clone(state.auditLog), clone(preview.auditEvent)],
    undoStack: [
      ...clone(state.undoStack),
      {
        objectId: preview.operation.object_id,
        before: clone(preview.before),
        after: clone(preview.after),
        auditEvent: clone(preview.auditEvent),
      },
    ],
    redoStack: [],
  };
  return nextState;
}

export function undoLastCommittedOperation(state: ReadAgentState): ReadAgentState {
  const last = state.undoStack.at(-1);
  if (!last) return state;
  const nextUndoStack = clone(state.undoStack.slice(0, -1));
  const nextObjects = {
    ...clone(state.objects),
    [last.objectId]: clone(last.before),
  };
  return {
    ...clone(state),
    objects: nextObjects,
    viewModelJson: buildViewModelJson(
      state.project,
      state.selectedBlueprintId,
      state.selectedFloorId,
      nextObjects,
    ),
    undoStack: nextUndoStack,
    redoStack: [...clone(state.redoStack), clone(last)],
  };
}

export function redoNextOperation(state: ReadAgentState): ReadAgentState {
  const next = state.redoStack.at(-1);
  if (!next) return state;
  const nextRedoStack = clone(state.redoStack.slice(0, -1));
  const nextObjects = {
    ...clone(state.objects),
    [next.objectId]: clone(next.after),
  };
  return {
    ...clone(state),
    objects: nextObjects,
    viewModelJson: buildViewModelJson(
      state.project,
      state.selectedBlueprintId,
      state.selectedFloorId,
      nextObjects,
    ),
    undoStack: [...clone(state.undoStack), clone(next)],
    redoStack: nextRedoStack,
  };
}

export function requestOcrCandidate(
  objectId: string,
  region: BBox,
): OcrCandidate {
  return {
    objectId,
    region,
    autoCommit: false,
    candidates: [
      {
        text: objectId === "beam-B3" ? "KL3(2)" : "L7",
        confidence: objectId === "beam-B3" ? 0.91 : 0.68,
        source: "POST /api/editor/ocr-region",
      },
      {
        text: objectId === "beam-B3" ? "KL3(?)" : "L?",
        confidence: objectId === "beam-B3" ? 0.63 : 0.44,
        source: "ocr_candidate_fallback",
      },
    ],
  };
}

export function selectFloor(
  state: ReadAgentState,
  floorId: string,
): ReadAgentState {
  const blueprints = getBlueprintsForFloor(state.project, floorId);
  const selectedBlueprintId = blueprints[0] ?? state.selectedBlueprintId;
  return {
    ...clone(state),
    selectedFloorId: floorId,
    selectedBlueprintId,
    viewModelJson: buildViewModelJson(
      state.project,
      selectedBlueprintId,
      floorId,
      state.objects,
    ),
  };
}

export function selectBlueprint(
  state: ReadAgentState,
  blueprintId: string,
): ReadAgentState {
  return {
    ...clone(state),
    selectedBlueprintId: blueprintId,
    viewModelJson: buildViewModelJson(
      state.project,
      blueprintId,
      state.selectedFloorId,
      state.objects,
    ),
  };
}
