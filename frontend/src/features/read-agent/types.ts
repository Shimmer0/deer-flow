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

export type ReviewStatus =
  | "reference"
  | "candidate"
  | "needs_review"
  | "accepted"
  | "rejected"
  | "human_confirmed";

export type BlueprintRecord = {
  blueprint_id: string;
  title: string;
  drawing_type: string;
  file_name: string;
  asset_ref: string;
  status: "uploaded" | "processing" | "ready_for_edit" | "failed";
  floor_id: string;
  building_id: string;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
};

export type FloorRecord = {
  floor_id: string;
  floor_name: string;
  floor_index: number;
  elevation_m?: number | null;
  floor_height_m?: number | null;
  blueprints: BlueprintRecord[];
  current_semantic_version?: string | null;
  current_view_model_asset?: string | null;
};

export type BuildingRecord = {
  building_id: string;
  building_name: string;
  floors: FloorRecord[];
};

export type ProjectRecord = {
  project_id: string;
  name: string;
  discipline: string;
  buildings: BuildingRecord[];
  created_at: string;
  updated_at: string;
};

export type ProjectSummary = {
  project_id: string;
  name: string;
  discipline: string;
  floor_ids: string[];
  blueprint_ids: string[];
  updated_at?: string;
};

export type RunRecord = {
  run_id: string;
  project_id: string;
  blueprint_ids: string[];
  floor_ids: string[];
  target_stages: string[];
  status: "queued" | "running" | "ready_for_edit" | "failed" | "cancelled";
  events_url: string;
  edit_base_version?: string | null;
  error?: string | null;
  artifact_refs?: Record<string, unknown>;
};

export type RunEvent = {
  seq: number;
  run_id: string;
  event_type: string;
  sseType?: string;
  project_id: string;
  floor_id?: string | null;
  blueprint_id?: string | null;
  stage?: string | null;
  title: string;
  summary?: string | null;
  payload?: Record<string, unknown>;
  artifact_refs?: string[];
  ts: string;
};

export type ViewGeometry =
  | { kind: "vertical_axis"; coord_mm: number }
  | { kind: "horizontal_axis"; coord_mm: number }
  | {
      kind: "rect_center";
      center_mm: [number, number];
      size_mm?: [number, number];
    }
  | { kind: "polyline"; points_mm: [number, number][] };

export type SemanticViewObject = {
  view_id: string;
  semantic_object_id: string;
  object_type:
    | "axis"
    | "column"
    | "main_beam"
    | "label"
    | "dimension_chain"
    | "secondary_beam_candidate"
    | "opening_candidate";
  layer: string;
  display_label?: string;
  label?: string;
  geometry: ViewGeometry;
  section?: { width_mm?: number; height_mm?: number } | string | null;
  section_text?: string;
  editable_fields?: string[];
  confidence?: number;
  review_status?: ReviewStatus;
  evidence_refs?: string[];
  source_blueprint_id?: string;
};

export type SemanticViewModel = {
  schema_version: string;
  project_id: string;
  floor_id: string;
  blueprint_ids: string[];
  base_json_version?: string | null;
  coordinate_system?: {
    unit: "mm";
    total_width_mm?: number;
    total_height_mm?: number;
  };
  layers: Array<{
    id: string;
    name: string;
    visible: boolean;
    locked?: boolean;
    opacity?: number;
  }>;
  objects: SemanticViewObject[];
  quality?: Record<string, unknown>;
  message?: string;
};

export type EditorOperation = {
  operation_id: string;
  operation_type:
    | "update_beam_section"
    | "update_beam_label"
    | "update_review_status"
    | "update_column_section"
    | "reject_object"
    | "accept_object";
  actor: { type: "human" | "agent"; id: string };
  target: { object_id: string; object_type: SemanticViewObject["object_type"] };
  params: Record<string, unknown>;
};

export type OperationPreview = {
  preview_result_id: string;
  project_id: string;
  floor_id: string;
  blueprint_id?: string | null;
  base_json_version: string;
  operation: EditorOperation;
  json_patch: Array<{ op: string; path: string; value: unknown }>;
  validation_result: {
    status: "passed" | "failed" | "review_required";
    rules: string[];
    errors: Array<Record<string, unknown>>;
    warnings: Array<Record<string, unknown>>;
  };
  audit_event: Record<string, unknown>;
  new_json_version?: string;
};
