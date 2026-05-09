"use client";

import { useEffect, useState } from "react";

import {
  allFloors,
  createUpdateOperation,
  findObject,
  formatSection,
  objectsForLayer,
  projectToSummary,
  viewBoxFor,
} from "./adapters";
import {
  assetUrl,
  commitOperation,
  createProject,
  createRun,
  getProject,
  getSemanticJson,
  getViewModel,
  listProjects,
  openRunEventSource,
  parseRunEvent,
  previewOperation,
  uploadBlueprints,
} from "./api";
import type {
  OperationPreview,
  ProjectRecord,
  ProjectSummary,
  RunEvent,
  SemanticViewModel,
  SemanticViewObject,
} from "./types";
import { SSE_EVENT_TYPES } from "./types";

type Mode = "processing" | "edit";

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-72 overflow-auto rounded bg-zinc-950 p-3 text-xs text-zinc-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function ProjectCreator({
  onCreated,
}: {
  onCreated: (project: ProjectRecord) => void;
}) {
  const [name, setName] = useState("结构图纸项目");
  const [buildingName, setBuildingName] = useState("主楼");
  const [busy, setBusy] = useState(false);
  return (
    <div className="rounded-lg border bg-white p-3">
      <h3 className="font-medium">1. 创建项目</h3>
      <div className="mt-2 grid gap-2 text-sm">
        <input
          className="rounded border px-2 py-1"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="项目名称"
        />
        <input
          className="rounded border px-2 py-1"
          value={buildingName}
          onChange={(event) => setBuildingName(event.target.value)}
          placeholder="建筑名称"
        />
        <button
          className="rounded bg-zinc-900 px-3 py-2 text-white disabled:opacity-50"
          disabled={busy || !name.trim()}
          onClick={async () => {
            setBusy(true);
            try {
              onCreated(
                await createProject({
                  name,
                  building_name: buildingName,
                  building_id: "B01",
                }),
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          创建真实项目
        </button>
      </div>
    </div>
  );
}

function UploadPanel({
  project,
  onUploaded,
}: {
  project: ProjectRecord | null;
  onUploaded: (project: ProjectRecord) => void;
}) {
  const [floorId, setFloorId] = useState("F03");
  const [floorName, setFloorName] = useState("三层");
  const [floorIndex, setFloorIndex] = useState(3);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  return (
    <div className="rounded-lg border bg-white p-3">
      <h3 className="font-medium">2. 上传多层蓝图</h3>
      <p className="mt-1 text-xs text-zinc-500">
        每次上传会绑定到一个楼层；同一项目可重复上传 F01/F02/F03/RF 等楼层图纸。
      </p>
      <div className="mt-2 grid gap-2 text-sm">
        <div className="grid grid-cols-3 gap-2">
          <input
            className="rounded border px-2 py-1"
            value={floorId}
            onChange={(event) => setFloorId(event.target.value)}
            placeholder="floor_id"
          />
          <input
            className="rounded border px-2 py-1"
            value={floorName}
            onChange={(event) => setFloorName(event.target.value)}
            placeholder="楼层名"
          />
          <input
            className="rounded border px-2 py-1"
            type="number"
            value={floorIndex}
            onChange={(event) => setFloorIndex(Number(event.target.value))}
          />
        </div>
        <input
          className="rounded border px-2 py-1"
          multiple
          type="file"
          accept="image/*,.pdf"
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
        />
        <button
          className="rounded bg-blue-700 px-3 py-2 text-white disabled:opacity-50"
          disabled={!project || !files.length || busy}
          onClick={async () => {
            if (!project) return;
            setBusy(true);
            try {
              onUploaded(
                await uploadBlueprints({
                  projectId: project.project_id,
                  files,
                  buildingId: project.buildings[0]?.building_id ?? "B01",
                  buildingName: project.buildings[0]?.building_name ?? "主楼",
                  floorId,
                  floorName,
                  floorIndex,
                  drawingType: "structural_plan",
                }),
              );
              setFiles([]);
            } finally {
              setBusy(false);
            }
          }}
        >
          上传到项目
        </button>
      </div>
    </div>
  );
}

function TracePanel({ events }: { events: RunEvent[] }) {
  return (
    <div className="min-h-0 rounded-lg border bg-white p-3">
      <h3 className="font-medium">Agent 实时公开过程</h3>
      <p className="mt-1 text-xs text-zinc-500">
        展示可审计的工具调用、产物和状态，不展示模型私有推理链。
      </p>
      <div className="mt-2 max-h-80 space-y-2 overflow-auto pr-1">
        {events.length === 0 && (
          <div className="rounded bg-zinc-50 p-3 text-sm text-zinc-500">
            尚未启动识图任务。
          </div>
        )}
        {events.map((event) => (
          <div
            key={`${event.run_id}-${event.seq}`}
            className="rounded border border-zinc-200 bg-zinc-50 p-2 text-xs"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-zinc-900">
                #{event.seq} {event.title}
              </span>
              <span className="rounded bg-white px-2 py-0.5 text-zinc-500">
                {event.event_type}
              </span>
            </div>
            {event.summary && (
              <p className="mt-1 text-zinc-600">{event.summary}</p>
            )}
            {!!event.artifact_refs?.length && (
              <p className="mt-1 text-zinc-500">
                artifacts: {event.artifact_refs.join(", ")}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function SemanticCanvas({
  objects,
  selectedId,
  viewModel,
  onSelect,
}: {
  objects: SemanticViewObject[];
  selectedId: string | null;
  viewModel: SemanticViewModel | null;
  onSelect: (id: string) => void;
}) {
  const axisObjects = objects.filter((object) => object.object_type === "axis");
  const columns = objectsForLayer(viewModel, "COLUMN");
  const beams = objectsForLayer(viewModel, "MAIN_BEAM");
  const width = Math.max(
    Number(viewModel?.coordinate_system?.total_width_mm ?? 50000),
    1000,
  );
  const height = Math.max(
    Number(viewModel?.coordinate_system?.total_height_mm ?? 42000),
    1000,
  );
  return (
    <svg
      className="h-full min-h-[420px] w-full rounded-lg border bg-white"
      viewBox={viewBoxFor(viewModel)}
    >
      <rect
        x={-2500}
        y={-2500}
        width={width + 5000}
        height={height + 5000}
        fill="#fafafa"
      />
      {axisObjects.map((object) => {
        if (object.geometry.kind === "vertical_axis") {
          return (
            <line
              key={object.view_id}
              x1={object.geometry.coord_mm}
              x2={object.geometry.coord_mm}
              y1={-1600}
              y2={height + 1600}
              stroke="#9ca3af"
              strokeDasharray="600 250 120 250"
              strokeWidth={80}
            />
          );
        }
        if (object.geometry.kind === "horizontal_axis") {
          return (
            <line
              key={object.view_id}
              x1={-1600}
              x2={width + 1600}
              y1={object.geometry.coord_mm}
              y2={object.geometry.coord_mm}
              stroke="#9ca3af"
              strokeDasharray="600 250 120 250"
              strokeWidth={80}
            />
          );
        }
        return null;
      })}
      {beams.map((object) => {
        if (object.geometry.kind !== "polyline") return null;
        const points = object.geometry.points_mm
          .map((point) => point.join(","))
          .join(" ");
        const selected = selectedId === object.semantic_object_id;
        const mid = object.geometry.points_mm[
          Math.floor(object.geometry.points_mm.length / 2)
        ] ??
          object.geometry.points_mm[0] ?? [0, 0];
        return (
          <g
            key={object.view_id}
            onClick={() => onSelect(object.semantic_object_id)}
            className="cursor-pointer"
          >
            <polyline
              points={points}
              fill="none"
              stroke={selected ? "#2563eb" : "#111827"}
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={selected ? 760 : 520}
              opacity={0.92}
            />
            <text
              x={mid[0] + 300}
              y={mid[1] - 450}
              fontSize={900}
              fill={selected ? "#2563eb" : "#111827"}
            >
              {object.display_label ?? object.semantic_object_id}
            </text>
          </g>
        );
      })}
      {columns.map((object) => {
        if (object.geometry.kind !== "rect_center") return null;
        const [cx, cy] = object.geometry.center_mm;
        const [w, h] = object.geometry.size_mm ?? [900, 900];
        const selected = selectedId === object.semantic_object_id;
        return (
          <g
            key={object.view_id}
            onClick={() => onSelect(object.semantic_object_id)}
            className="cursor-pointer"
          >
            <rect
              x={cx - w / 2}
              y={cy - h / 2}
              width={w}
              height={h}
              fill={selected ? "#dbeafe" : "#e5e7eb"}
              stroke={selected ? "#2563eb" : "#111827"}
              strokeWidth={120}
            />
          </g>
        );
      })}
    </svg>
  );
}

function OriginalCompare({
  project,
  floorId,
}: {
  project: ProjectRecord | null;
  floorId: string | null;
}) {
  const floor = allFloors(project).find((item) => item.floor_id === floorId);
  return (
    <div className="rounded-lg border bg-white p-3">
      <h3 className="font-medium">原图蓝图对比</h3>
      <div className="mt-2 grid max-h-80 gap-2 overflow-auto">
        {!floor?.blueprints.length && (
          <div className="text-sm text-zinc-500">当前楼层没有上传图纸。</div>
        )}
        {floor?.blueprints.map((blueprint) => (
          <div key={blueprint.blueprint_id} className="rounded border p-2">
            <div className="mb-1 text-xs font-medium">
              {blueprint.title} · {blueprint.status}
            </div>
            {blueprint.asset_ref.toLowerCase().endsWith(".pdf") ? (
              <a
                className="text-xs text-blue-700 underline"
                href={assetUrl(blueprint.asset_ref)}
                target="_blank"
              >
                打开 PDF
              </a>
            ) : (
              <img
                className="max-h-56 w-full object-contain"
                src={assetUrl(blueprint.asset_ref)}
                alt={blueprint.title}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Inspector({
  object,
  projectId,
  floorId,
  blueprintId,
  baseJsonVersion,
  onCommitted,
}: {
  object: SemanticViewObject | null;
  projectId: string | null;
  floorId: string | null;
  blueprintId?: string;
  baseJsonVersion?: string | null;
  onCommitted: () => void;
}) {
  const [sectionText, setSectionText] = useState("");
  const [preview, setPreview] = useState<OperationPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setSectionText(formatSection(object?.section));
    setPreview(null);
    setError(null);
  }, [object?.section, object?.semantic_object_id]);
  if (!object)
    return (
      <div className="rounded-lg border bg-white p-3 text-sm text-zinc-500">
        选择梁或柱后可编辑属性。
      </div>
    );
  const editable =
    object.object_type === "main_beam" || object.object_type === "column";
  return (
    <div className="rounded-lg border bg-white p-3">
      <h3 className="font-medium">对象属性与保存</h3>
      <div className="mt-2 space-y-2 text-sm">
        <div>
          <span className="text-zinc-500">ID：</span>
          {object.semantic_object_id}
        </div>
        <div>
          <span className="text-zinc-500">类型：</span>
          {object.object_type}
        </div>
        <div>
          <span className="text-zinc-500">状态：</span>
          {object.review_status ?? "needs_review"}
        </div>
        <div>
          <span className="text-zinc-500">置信度：</span>
          {object.confidence ?? "-"}
        </div>
        {editable && (
          <label className="block">
            <span className="text-zinc-500">截面，例如 600x1200</span>
            <input
              className="mt-1 w-full rounded border px-2 py-1"
              value={sectionText}
              onChange={(event) => setSectionText(event.target.value)}
            />
          </label>
        )}
        <div className="flex gap-2">
          <button
            className="rounded bg-blue-700 px-3 py-1.5 text-white disabled:opacity-50"
            disabled={!editable || !projectId || !floorId}
            onClick={async () => {
              setError(null);
              const op = createUpdateOperation({
                object,
                sectionText,
                reviewStatus: "human_confirmed",
              });
              if (!op || !projectId || !floorId) {
                setError("无法生成 Operation，请检查截面格式。列如 600x1200。");
                return;
              }
              try {
                setPreview(
                  await previewOperation({
                    projectId,
                    floorId,
                    blueprintId,
                    baseJsonVersion,
                    operation: op,
                  }),
                );
              } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
              }
            }}
          >
            预览修改
          </button>
          <button
            className="rounded bg-emerald-700 px-3 py-1.5 text-white disabled:opacity-50"
            disabled={
              !preview ||
              preview.validation_result.status === "failed" ||
              !projectId ||
              !floorId
            }
            onClick={async () => {
              if (!preview || !projectId || !floorId) return;
              try {
                await commitOperation({
                  projectId,
                  floorId,
                  blueprintId,
                  baseJsonVersion: preview.base_json_version,
                  previewResultId: preview.preview_result_id,
                  operation: preview.operation,
                });
                setPreview(null);
                onCommitted();
              } catch (err) {
                setError(err instanceof Error ? err.message : String(err));
              }
            }}
          >
            确认保存
          </button>
        </div>
        {error && (
          <div className="rounded bg-red-50 p-2 text-xs text-red-700">
            {error}
          </div>
        )}
        {preview && (
          <div>
            <div className="mb-1 text-xs font-medium">
              Patch 预览 · {preview.validation_result.status}
            </div>
            <JsonBlock
              value={{
                json_patch: preview.json_patch,
                validation_result: preview.validation_result,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export function ReadAgentWorkbench() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [selectedFloorId, setSelectedFloorId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("processing");
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [viewModel, setViewModel] = useState<SemanticViewModel | null>(null);
  const [semanticJson, setSemanticJson] = useState<unknown>(null);
  const [selectedObjectId, setSelectedObjectId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch((err) => setError(err.message));
  }, []);

  const floors = allFloors(project);
  const selectedObject = findObject(viewModel, selectedObjectId);
  const firstBlueprintId = floors.find(
    (floor) => floor.floor_id === selectedFloorId,
  )?.blueprints[0]?.blueprint_id;

  async function reloadProject(
    projectId = project?.project_id,
    floorId = selectedFloorId,
  ) {
    if (!projectId) return;
    const loaded = await getProject(projectId);
    setProject(loaded);
    const nextFloorId = floorId ?? allFloors(loaded)[0]?.floor_id ?? null;
    setSelectedFloorId(nextFloorId);
    if (nextFloorId) {
      const vm = await getViewModel(projectId, nextFloorId);
      setViewModel(vm);
      setSelectedObjectId(
        vm.objects.find((object) => object.object_type === "main_beam")
          ?.semantic_object_id ??
          vm.objects[0]?.semantic_object_id ??
          null,
      );
      try {
        setSemanticJson(await getSemanticJson(projectId, nextFloorId));
      } catch {
        setSemanticJson(null);
      }
    }
  }

  async function startRun() {
    if (!project) return;
    setBusy(true);
    setError(null);
    setEvents([]);
    setMode("processing");
    try {
      const run = await createRun({
        projectId: project.project_id,
        floorIds: selectedFloorId ? [selectedFloorId] : undefined,
      });
      const source = openRunEventSource(run.run_id);
      const handle = async (message: MessageEvent<string>) => {
        const event = parseRunEvent(message);
        if (!event) return;
        setEvents((old) => [...old, event]);
        if (event.event_type === "ready_for_edit") {
          source.close();
          await reloadProject(project.project_id, selectedFloorId);
          setMode("edit");
          setBusy(false);
        }
        if (
          event.event_type === "run.failed" ||
          event.event_type === "stream.closed"
        ) {
          source.close();
          setBusy(false);
        }
      };
      source.onmessage = handle;
      for (const type of SSE_EVENT_TYPES)
        source.addEventListener(type, handle as unknown as EventListener);
      source.onerror = () => {
        source.close();
        setBusy(false);
        setError("事件流连接中断，请检查后端日志或刷新运行状态。");
      };
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const semanticObjects = viewModel?.objects ?? [];

  return (
    <div className="flex h-full min-h-[calc(100vh-1rem)] flex-col bg-zinc-100 p-3 text-zinc-900">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-white px-4 py-3">
        <div>
          <h1 className="text-lg font-semibold">
            CV-NotFunning 结构图纸读图 Agent
          </h1>
          <p className="text-xs text-zinc-500">
            真实闭环：上传多层蓝图 → Agent 识图 → 实时可视化 → 语义编辑 → JSON
            持久化。
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm">
          <span
            className={classNames(
              "rounded px-2 py-1",
              mode === "processing"
                ? "bg-amber-100 text-amber-800"
                : "bg-emerald-100 text-emerald-800",
            )}
          >
            {mode === "processing" ? "Processing Mode" : "Edit Mode"}
          </span>
          <button
            className="rounded border px-3 py-1.5"
            onClick={() => void listProjects().then(setProjects)}
          >
            刷新项目
          </button>
        </div>
      </header>
      {error && (
        <div className="mb-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}
      <main className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[360px_minmax(0,1fr)_360px]">
        <aside className="min-h-0 space-y-3 overflow-auto">
          <ProjectCreator
            onCreated={(created) => {
              setProject(created);
              setProjects((old) => [
                projectToSummary(created),
                ...old.filter((item) => item.project_id !== created.project_id),
              ]);
              setSelectedFloorId(null);
              setViewModel(null);
            }}
          />
          <div className="rounded-lg border bg-white p-3">
            <h3 className="font-medium">选择已有项目</h3>
            <select
              className="mt-2 w-full rounded border px-2 py-1 text-sm"
              value={project?.project_id ?? ""}
              onChange={async (event) => {
                if (!event.target.value) return;
                await reloadProject(event.target.value, null);
              }}
            >
              <option value="">请选择</option>
              {projects.map((item) => (
                <option key={item.project_id} value={item.project_id}>
                  {item.name} · {item.project_id}
                </option>
              ))}
            </select>
          </div>
          <UploadPanel
            project={project}
            onUploaded={(updated) => {
              setProject(updated);
              setSelectedFloorId(allFloors(updated).at(-1)?.floor_id ?? null);
            }}
          />
          <div className="rounded-lg border bg-white p-3">
            <h3 className="font-medium">3. 楼层与识图</h3>
            <select
              className="mt-2 w-full rounded border px-2 py-1 text-sm"
              value={selectedFloorId ?? ""}
              onChange={async (event) => {
                setSelectedFloorId(event.target.value);
                if (project)
                  await reloadProject(project.project_id, event.target.value);
              }}
            >
              <option value="">选择楼层</option>
              {floors.map((floor) => (
                <option key={floor.floor_id} value={floor.floor_id}>
                  {floor.floor_name} · {floor.floor_id} ·{" "}
                  {floor.blueprints.length} 张图
                </option>
              ))}
            </select>
            <button
              className="mt-2 w-full rounded bg-indigo-700 px-3 py-2 text-white disabled:opacity-50"
              disabled={!project || !selectedFloorId || busy}
              onClick={() => void startRun()}
            >
              启动真实 Agent 识图
            </button>
          </div>
          <TracePanel events={events} />
        </aside>

        <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_240px] gap-3">
          <div className="rounded-lg border bg-white p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="font-medium">语义结构图</h2>
                <p className="text-xs text-zinc-500">
                  对象数：{semanticObjects.length}
                  ；编辑对象是梁/柱/轴网等语义对象，不是 CAD 自由点线。
                </p>
              </div>
              <div className="flex gap-2 text-xs">
                <button
                  className="rounded border px-2 py-1"
                  onClick={() => setMode("processing")}
                >
                  查看处理过程
                </button>
                <button
                  className="rounded border px-2 py-1"
                  onClick={() => setMode("edit")}
                  disabled={!viewModel?.objects.length}
                >
                  进入编辑模式
                </button>
              </div>
            </div>
          </div>
          <div className="min-h-0">
            <SemanticCanvas
              objects={semanticObjects}
              selectedId={selectedObjectId}
              viewModel={viewModel}
              onSelect={setSelectedObjectId}
            />
          </div>
          <div className="grid min-h-0 gap-3 md:grid-cols-2">
            <div className="min-h-0 rounded-lg border bg-white p-3">
              <h3 className="font-medium">对象列表</h3>
              <div className="mt-2 max-h-44 overflow-auto text-xs">
                {semanticObjects.map((object) => (
                  <button
                    key={object.semantic_object_id}
                    className={classNames(
                      "mb-1 block w-full rounded border px-2 py-1 text-left",
                      selectedObjectId === object.semantic_object_id &&
                        "border-blue-500 bg-blue-50",
                    )}
                    onClick={() =>
                      setSelectedObjectId(object.semantic_object_id)
                    }
                  >
                    {object.object_type} ·{" "}
                    {object.display_label ?? object.semantic_object_id}
                  </button>
                ))}
              </div>
            </div>
            <div className="min-h-0 rounded-lg border bg-white p-3">
              <h3 className="font-medium">JSON 实时状态</h3>
              <JsonBlock
                value={{
                  view_quality: viewModel?.quality,
                  base_json_version: viewModel?.base_json_version,
                  selected: selectedObject,
                }}
              />
            </div>
          </div>
        </section>

        <aside className="min-h-0 space-y-3 overflow-auto">
          <OriginalCompare project={project} floorId={selectedFloorId} />
          <Inspector
            object={selectedObject}
            projectId={project?.project_id ?? null}
            floorId={selectedFloorId}
            blueprintId={firstBlueprintId}
            baseJsonVersion={viewModel?.base_json_version}
            onCommitted={() =>
              void reloadProject(project?.project_id, selectedFloorId)
            }
          />
          <div className="rounded-lg border bg-white p-3">
            <h3 className="font-medium">楼层 3D 预览入口</h3>
            <p className="mt-1 text-xs text-zinc-500">
              当前补丁只打通 2D 语义编辑闭环；3D 只读预览应从 floor-level
              semantic JSON 派生，禁止反向编辑。
            </p>
          </div>
          <details className="rounded-lg border bg-white p-3">
            <summary className="cursor-pointer font-medium">
              Semantic JSON
            </summary>
            <div className="mt-2">
              <JsonBlock
                value={semanticJson ?? { message: "识图完成后加载" }}
              />
            </div>
          </details>
        </aside>
      </main>
    </div>
  );
}

export function ReadAgentChatPanel() {
  return <ReadAgentWorkbench />;
}
