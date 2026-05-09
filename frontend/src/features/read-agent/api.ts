import type {
  EditorOperation,
  OperationPreview,
  ProjectRecord,
  ProjectSummary,
  RunEvent,
  RunRecord,
  SemanticViewModel,
} from "./types";

export const READ_AGENT_API_PREFIX = "/api/read-agent";

function getCookieValue(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  if (!match) return null;
  return decodeURIComponent(match.slice(prefix.length));
}

function csrfHeader(init?: RequestInit): Record<string, string> {
  const method = (init?.method ?? "GET").toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return {};
  const token = getCookieValue("csrf_token");
  return token ? { "X-CSRF-Token": token } : {};
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: init?.credentials ?? "same-origin",
    headers: {
      ...(init?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...csrfHeader(init),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return (await response.json()) as T;
}

export function assetUrl(assetRef: string): string {
  return `${READ_AGENT_API_PREFIX}/assets/${assetRef.split("/").map(encodeURIComponent).join("/")}`;
}

export async function createProject(input: {
  name: string;
  discipline?: string;
  building_id?: string;
  building_name?: string;
}): Promise<ProjectRecord> {
  const result = await jsonFetch<{ project: ProjectRecord }>(
    `${READ_AGENT_API_PREFIX}/projects`,
    {
      method: "POST",
      body: JSON.stringify({
        discipline: "structure",
        building_id: "B01",
        building_name: "主楼",
        ...input,
      }),
    },
  );
  return result.project;
}

export async function listProjects(): Promise<ProjectSummary[]> {
  const result = await jsonFetch<{ projects: ProjectSummary[] }>(
    `${READ_AGENT_API_PREFIX}/projects`,
  );
  return result.projects;
}

export async function getProject(projectId: string): Promise<ProjectRecord> {
  return jsonFetch<ProjectRecord>(
    `${READ_AGENT_API_PREFIX}/projects/${encodeURIComponent(projectId)}`,
  );
}

export async function uploadBlueprints(input: {
  projectId: string;
  files: File[];
  buildingId: string;
  buildingName: string;
  floorId: string;
  floorName: string;
  floorIndex: number;
  drawingType: string;
  elevationM?: number | null;
  floorHeightM?: number | null;
}): Promise<ProjectRecord> {
  const form = new FormData();
  for (const file of input.files) form.append("files", file);
  form.append("building_id", input.buildingId);
  form.append("building_name", input.buildingName);
  form.append("floor_id", input.floorId);
  form.append("floor_name", input.floorName);
  form.append("floor_index", String(input.floorIndex));
  form.append("drawing_type", input.drawingType);
  if (input.elevationM !== undefined && input.elevationM !== null)
    form.append("elevation_m", String(input.elevationM));
  if (input.floorHeightM !== undefined && input.floorHeightM !== null)
    form.append("floor_height_m", String(input.floorHeightM));
  const result = await jsonFetch<{ project: ProjectRecord }>(
    `${READ_AGENT_API_PREFIX}/projects/${encodeURIComponent(input.projectId)}/blueprints`,
    { method: "POST", body: form },
  );
  return result.project;
}

export async function createRun(input: {
  projectId: string;
  floorIds?: string[];
  blueprintIds?: string[];
  targetStages?: string[];
}): Promise<RunRecord> {
  return jsonFetch<RunRecord>(`${READ_AGENT_API_PREFIX}/runs`, {
    method: "POST",
    body: JSON.stringify({
      project_id: input.projectId,
      floor_ids: input.floorIds,
      blueprint_ids: input.blueprintIds,
      target_stages: input.targetStages ?? ["stage1", "stage2", "stage3"],
    }),
  });
}

export function openRunEventSource(runId: string): EventSource {
  return new EventSource(
    `${READ_AGENT_API_PREFIX}/runs/${encodeURIComponent(runId)}/events`,
  );
}

export async function getViewModel(
  projectId: string,
  floorId: string,
): Promise<SemanticViewModel> {
  return jsonFetch<SemanticViewModel>(
    `${READ_AGENT_API_PREFIX}/projects/${encodeURIComponent(projectId)}/floors/${encodeURIComponent(floorId)}/view-model`,
  );
}

export async function getSemanticJson(
  projectId: string,
  floorId: string,
): Promise<unknown> {
  return jsonFetch<unknown>(
    `${READ_AGENT_API_PREFIX}/projects/${encodeURIComponent(projectId)}/floors/${encodeURIComponent(floorId)}/semantic-json`,
  );
}

export async function previewOperation(input: {
  projectId: string;
  floorId: string;
  blueprintId?: string;
  baseJsonVersion?: string | null;
  operation: EditorOperation;
}): Promise<OperationPreview> {
  return jsonFetch<OperationPreview>(
    `${READ_AGENT_API_PREFIX}/editor/operations/preview`,
    {
      method: "POST",
      body: JSON.stringify({
        project_id: input.projectId,
        floor_id: input.floorId,
        blueprint_id: input.blueprintId,
        base_json_version: input.baseJsonVersion,
        operation: input.operation,
      }),
    },
  );
}

export async function commitOperation(input: {
  projectId: string;
  floorId: string;
  blueprintId?: string;
  baseJsonVersion?: string | null;
  previewResultId: string;
  operation: EditorOperation;
}): Promise<OperationPreview> {
  return jsonFetch<OperationPreview>(
    `${READ_AGENT_API_PREFIX}/editor/operations/commit`,
    {
      method: "POST",
      body: JSON.stringify({
        project_id: input.projectId,
        floor_id: input.floorId,
        blueprint_id: input.blueprintId,
        base_json_version: input.baseJsonVersion,
        preview_result_id: input.previewResultId,
        operation: input.operation,
        user_confirmation: true,
      }),
    },
  );
}

export function parseRunEvent(event: MessageEvent<string>): RunEvent | null {
  try {
    return JSON.parse(event.data) as RunEvent;
  } catch {
    return null;
  }
}
