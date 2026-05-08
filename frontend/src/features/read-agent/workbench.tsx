"use client";

import {
  Activity,
  AlertTriangle,
  Box,
  CheckCircle2,
  FileJson,
  GitBranch,
  Layers,
  Pencil,
  Redo2,
  Search,
  Undo2,
  Wifi,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { WebGLRenderer } from "three";

import {
  ACCEPTANCE_MATRIX,
  REST_ENDPOINTS,
  type ReviewStatus,
  type SemanticObject,
  createInitialReadAgentState,
  createOperationPreview,
  commitOperationPreview,
  getBlueprintsForFloor,
  getSchematic3dNotice,
  redoNextOperation,
  requestOcrCandidate,
  selectBlueprint,
  selectFloor,
  undoLastCommittedOperation,
} from "./model";

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

function statusClass(status: ReviewStatus) {
  if (status === "accepted") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "rejected") return "border-red-200 bg-red-50 text-red-700";
  if (status === "candidate") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-blue-200 bg-blue-50 text-blue-700";
}

function objectsOnSelection(
  objects: Record<string, SemanticObject>,
  floorId: string,
  blueprintId: string,
) {
  return Object.values(objects).filter(
    (object) => object.floorId === floorId && object.blueprintId === blueprintId,
  );
}

function formatJson(value: unknown) {
  return JSON.stringify(value, null, 2);
}

export function ReadAgentWorkbench() {
  const [state, setState] = useState(createInitialReadAgentState);
  const [mode, setMode] = useState<"processing" | "edit">("processing");
  const [traceCount, setTraceCount] = useState(state.publicTraceEvents.length);
  const [isReplaying, setIsReplaying] = useState(false);
  const [selectedObjectId, setSelectedObjectId] = useState("beam-B3");
  const [jsonTab, setJsonTab] = useState<"stage" | "view" | "patch" | "audit">(
    "stage",
  );
  const [draft, setDraft] = useState({
    label: "KL3(2)",
    section: "300x650",
    reviewStatus: "needs_review" as ReviewStatus,
  });

  const selectionObjects = useMemo(
    () =>
      objectsOnSelection(
        state.objects,
        state.selectedFloorId,
        state.selectedBlueprintId,
      ),
    [state.objects, state.selectedBlueprintId, state.selectedFloorId],
  );
  const selectedObject = state.objects[selectedObjectId] ?? selectionObjects[0];
  const selectedBeam = selectedObject?.type === "beam" ? selectedObject : null;
  const schematicNotice = getSchematic3dNotice(
    state.project,
    state.selectedFloorId,
  );

  useEffect(() => {
    if (!selectionObjects.some((object) => object.id === selectedObjectId)) {
      setSelectedObjectId(selectionObjects[0]?.id ?? "beam-B3");
    }
  }, [selectedObjectId, selectionObjects]);

  useEffect(() => {
    if (selectedBeam) {
      setDraft({
        label: selectedBeam.label,
        section: selectedBeam.section,
        reviewStatus: selectedBeam.reviewStatus,
      });
    }
  }, [selectedBeam]);

  useEffect(() => {
    if (!isReplaying) return;
    if (traceCount >= state.publicTraceEvents.length) {
      setIsReplaying(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setTraceCount((count) =>
        Math.min(count + 1, state.publicTraceEvents.length),
      );
    }, 450);
    return () => window.clearTimeout(timer);
  }, [isReplaying, state.publicTraceEvents.length, traceCount]);

  const preview = useMemo(() => {
    if (!selectedBeam) return null;
    return createOperationPreview(state, {
      objectId: selectedBeam.id,
      updates: draft,
      actor: "web-ui-user",
    });
  }, [draft, selectedBeam, state]);

  const visibleTrace = state.publicTraceEvents.slice(0, traceCount);
  const floorBlueprintIds = getBlueprintsForFloor(
    state.project,
    state.selectedFloorId,
  );

  function handleFloorChange(floorId: string) {
    setState((current) => selectFloor(current, floorId));
    setJsonTab("view");
  }

  function handleBlueprintChange(blueprintId: string) {
    setState((current) => selectBlueprint(current, blueprintId));
    setJsonTab("view");
  }

  function handleCommit() {
    if (!preview) return;
    setState((current) => commitOperationPreview(current, preview));
    setJsonTab("audit");
    setMode("edit");
  }

  function handleOcr() {
    if (!selectedObject?.evidenceRef) return;
    const candidate = requestOcrCandidate(
      selectedObject.id,
      selectedObject.evidenceRef.bbox,
    );
    setState((current) => ({
      ...current,
      ocrCandidates: [candidate, ...current.ocrCandidates],
    }));
  }

  return (
    <main className="min-h-screen bg-zinc-50 text-zinc-950" data-testid="read-agent-workbench">
      <header className="sticky top-0 z-20 border-b bg-white/95 backdrop-blur">
        <div className="flex flex-col gap-3 px-4 py-3 lg:px-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h1 className="text-lg font-semibold tracking-normal">
                Read Agent WebUI
              </h1>
              <div className="text-sm text-zinc-600">
                {state.project.name} · {state.project.discipline} ·{" "}
                {state.project.buildingName}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-700">
                {state.editBaseVersion}
              </span>
              <span className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-blue-700">
                {state.stageJson.stage}
              </span>
              {schematicNotice && (
                <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-amber-700">
                  <AlertTriangle className="size-4" />
                  {schematicNotice}
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="floor_id"
              className="h-9 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={state.selectedFloorId}
              onChange={(event) => handleFloorChange(event.target.value)}
            >
              {state.project.floors.map((floor) => (
                <option key={floor.id} value={floor.id}>
                  {floor.id} · {floor.name}
                </option>
              ))}
            </select>
            <select
              aria-label="blueprint_id"
              className="h-9 rounded-md border border-zinc-300 bg-white px-3 text-sm"
              value={state.selectedBlueprintId}
              onChange={(event) => handleBlueprintChange(event.target.value)}
            >
              {floorBlueprintIds.map((blueprintId) => (
                <option key={blueprintId} value={blueprintId}>
                  {blueprintId}
                </option>
              ))}
            </select>
            <div className="inline-flex h-9 overflow-hidden rounded-md border border-zinc-300 bg-white">
              <button
                className={cx(
                  "inline-flex items-center gap-2 px-3 text-sm",
                  mode === "processing" && "bg-zinc-900 text-white",
                )}
                onClick={() => setMode("processing")}
                type="button"
              >
                <Activity className="size-4" />
                Processing
              </button>
              <button
                className={cx(
                  "inline-flex items-center gap-2 px-3 text-sm",
                  mode === "edit" && "bg-zinc-900 text-white",
                )}
                disabled={!state.baseVersionLocked}
                onClick={() => setMode("edit")}
                type="button"
              >
                <Pencil className="size-4" />
                Edit
              </button>
            </div>
            <button
              className="inline-flex h-9 items-center gap-2 rounded-md border border-zinc-300 bg-white px-3 text-sm hover:bg-zinc-100"
              onClick={() => {
                setTraceCount(1);
                setIsReplaying(true);
                setMode("processing");
              }}
              type="button"
            >
              <Wifi className="size-4" />
              Replay SSE
            </button>
          </div>
        </div>
      </header>

      <section className="grid gap-4 px-4 py-4 lg:grid-cols-[300px_minmax(0,1fr)_340px] lg:px-6">
        <AgentPanel events={visibleTrace} traceCount={traceCount} />

        <section className="min-w-0 space-y-4">
          <div className="rounded-lg border border-zinc-200 bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
              <div className="inline-flex items-center gap-2 text-sm font-medium">
                <Layers className="size-4 text-blue-600" />
                Semantic Canvas 2D
              </div>
              <div className="flex flex-wrap gap-2">
                {selectionObjects.map((object) => (
                  <button
                    className={cx(
                      "rounded-md border px-2 py-1 text-xs",
                      object.id === selectedObject?.id
                        ? "border-zinc-900 bg-zinc-900 text-white"
                        : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-100",
                    )}
                    key={object.id}
                    onClick={() => setSelectedObjectId(object.id)}
                    type="button"
                  >
                    {object.label}
                  </button>
                ))}
              </div>
            </div>
            <SemanticCanvas2D
              objects={selectionObjects}
              selectedObjectId={selectedObject?.id}
              onSelect={setSelectedObjectId}
            />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <ThreeDPreviewPanel
              objects={Object.values(state.objects)}
              project={state.project}
              selectedFloorId={state.selectedFloorId}
            />
            <JsonLivePanel
              activeTab={jsonTab}
              onTabChange={setJsonTab}
              patch={preview?.jsonPatch ?? []}
              state={state}
            />
          </div>
        </section>

        <InspectorPanel
          draft={draft}
          mode={mode}
          onCommit={handleCommit}
          onDraftChange={setDraft}
          onOcr={handleOcr}
          onRedo={() => setState((current) => redoNextOperation(current))}
          onUndo={() => setState((current) => undoLastCommittedOperation(current))}
          preview={preview}
          selectedObject={selectedObject}
          undoDisabled={state.undoStack.length === 0}
          redoDisabled={state.redoStack.length === 0}
        />
      </section>

      <section className="grid gap-4 px-4 pb-6 lg:grid-cols-[minmax(0,1fr)_340px] lg:px-6">
        <AuditPanel state={state} />
        <ContractPanel />
      </section>
    </main>
  );
}

function AgentPanel({
  events,
  traceCount,
}: {
  events: ReturnType<typeof createInitialReadAgentState>["publicTraceEvents"];
  traceCount: number;
}) {
  return (
    <aside className="rounded-lg border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="inline-flex items-center gap-2 text-sm font-medium">
          <Activity className="size-4 text-emerald-600" />
          Public Agent Trace
        </div>
        <span className="text-xs text-zinc-500">{traceCount}/8</span>
      </div>
      <div className="max-h-[690px] space-y-3 overflow-auto p-3">
        {events.map((event) => (
          <article className="rounded-md border border-zinc-200 p-3" key={event.seq}>
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="rounded-md bg-zinc-100 px-2 py-1 text-xs text-zinc-700">
                {event.sseType}
              </span>
              <span className="text-xs text-zinc-500">{event.stage}</span>
            </div>
            <h2 className="text-sm font-medium">{event.title}</h2>
            <p className="mt-1 text-sm text-zinc-600">{event.summary}</p>
            <p className="mt-2 border-l-2 border-blue-200 pl-2 text-xs text-zinc-500">
              {event.publicRationale}
            </p>
          </article>
        ))}
      </div>
    </aside>
  );
}

function SemanticCanvas2D({
  objects,
  onSelect,
  selectedObjectId,
}: {
  objects: SemanticObject[];
  onSelect: (id: string) => void;
  selectedObjectId?: string;
}) {
  const extentX = 49200;
  const extentY = 41700;
  const toX = (x: number) => x;
  const toY = (y: number) => extentY - y;

  return (
    <div className="relative aspect-[16/10] min-h-[360px] overflow-hidden bg-zinc-100">
      <svg
        aria-label="semantic structure canvas"
        className="h-full w-full"
        viewBox={`-1800 -1800 ${extentX + 3600} ${extentY + 3600}`}
      >
        <defs>
          <pattern id="minor-grid" width="2400" height="2400" patternUnits="userSpaceOnUse">
            <path d="M 2400 0 L 0 0 0 2400" fill="none" stroke="#e4e4e7" strokeWidth="80" />
          </pattern>
        </defs>
        <rect
          fill="url(#minor-grid)"
          height={extentY}
          opacity="0.95"
          width={extentX}
          x="0"
          y="0"
        />
        <rect
          fill="#eff6ff"
          height={extentY}
          opacity="0.55"
          stroke="#bfdbfe"
          strokeWidth="120"
          width={extentX}
          x="0"
          y="0"
        />
        {[0, 7200, 16200, 25200, 32400, 39600, 49200].map((x, index) => (
          <g key={`x-${x}`}>
            <line
              stroke="#71717a"
              strokeDasharray="480 360"
              strokeWidth="90"
              x1={toX(x)}
              x2={toX(x)}
              y1={toY(0)}
              y2={toY(extentY)}
            />
            <circle cx={toX(x)} cy={toY(extentY) - 900} fill="#fff" r="620" stroke="#52525b" strokeWidth="90" />
            <text dominantBaseline="middle" fill="#18181b" fontSize="760" textAnchor="middle" x={toX(x)} y={toY(extentY) - 900}>
              {index + 1}
            </text>
          </g>
        ))}
        {[0, 9600, 19200, 22500, 32100, 41700].map((y, index) => (
          <g key={`y-${y}`}>
            <line
              stroke="#71717a"
              strokeDasharray="480 360"
              strokeWidth="90"
              x1={toX(0)}
              x2={toX(extentX)}
              y1={toY(y)}
              y2={toY(y)}
            />
            <circle cx={toX(0) + 900} cy={toY(y)} fill="#fff" r="620" stroke="#52525b" strokeWidth="90" />
            <text dominantBaseline="middle" fill="#18181b" fontSize="760" textAnchor="middle" x={toX(0) + 900} y={toY(y)}>
              {"ABCDEF"[index]}
            </text>
          </g>
        ))}
        {objects.map((object) => (
          <SemanticObjectShape
            key={object.id}
            object={object}
            onSelect={onSelect}
            selected={object.id === selectedObjectId}
            toX={toX}
            toY={toY}
          />
        ))}
      </svg>
    </div>
  );
}

function SemanticObjectShape({
  object,
  onSelect,
  selected,
  toX,
  toY,
}: {
  object: SemanticObject;
  onSelect: (id: string) => void;
  selected: boolean;
  toX: (value: number) => number;
  toY: (value: number) => number;
}) {
  const stroke = selected ? "#dc2626" : object.type === "beam" ? "#2563eb" : "#111827";
  const strokeWidth = selected ? 420 : 260;

  if (object.type === "beam") {
    const [[x1, y1], [x2, y2]] = object.lineMm;
    return (
      <g className="cursor-pointer" onClick={() => onSelect(object.id)}>
        <line
          stroke={stroke}
          strokeLinecap="round"
          strokeWidth={strokeWidth}
          x1={toX(x1)}
          x2={toX(x2)}
          y1={toY(y1)}
          y2={toY(y2)}
        />
        {object.evidenceRef && (
          <rect
            fill="#fef3c7"
            height={object.evidenceRef.bbox.height}
            opacity="0.55"
            stroke="#d97706"
            strokeDasharray="180 160"
            strokeWidth="90"
            width={object.evidenceRef.bbox.width}
            x={object.evidenceRef.bbox.x}
            y={toY(object.evidenceRef.bbox.y) - object.evidenceRef.bbox.height}
          />
        )}
        <text
          fill="#1e3a8a"
          fontSize="920"
          fontWeight="700"
          textAnchor="middle"
          x={(toX(x1) + toX(x2)) / 2}
          y={toY(y1) - 650}
        >
          {object.label}
        </text>
      </g>
    );
  }

  if (object.type === "column") {
    return (
      <rect
        className="cursor-pointer"
        fill={selected ? "#fecaca" : "#e5e7eb"}
        height="980"
        onClick={() => onSelect(object.id)}
        stroke={stroke}
        strokeWidth="160"
        width="980"
        x={toX(object.coordMm[0]) - 490}
        y={toY(object.coordMm[1]) - 490}
      />
    );
  }

  if (object.type === "label") {
    return (
      <text
        className="cursor-pointer"
        fill={selected ? "#dc2626" : "#52525b"}
        fontSize="720"
        onClick={() => onSelect(object.id)}
        x={toX(object.coordMm[0])}
        y={toY(object.coordMm[1])}
      >
        {object.text}
      </text>
    );
  }

  return null;
}

function ThreeDPreviewPanel({
  objects,
  project,
  selectedFloorId,
}: {
  objects: SemanticObject[];
  project: ReturnType<typeof createInitialReadAgentState>["project"];
  selectedFloorId: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const notice = getSchematic3dNotice(project, selectedFloorId);

  useEffect(() => {
    let disposed = false;
    let animationFrame = 0;
    let renderer: WebGLRenderer | null = null;

    void import("three").then((THREE) => {
      if (disposed || !canvasRef.current) return;
      const canvas = canvasRef.current;
      const scene = new THREE.Scene();
      const group = new THREE.Group();
      scene.add(group);

      const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
      camera.position.set(19, 15, 24);
      camera.lookAt(0, 2, 0);

      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        canvas,
        preserveDrawingBuffer: true,
      });
      renderer.setClearColor(0xffffff, 0);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

      scene.add(new THREE.HemisphereLight(0xffffff, 0xbfd7ff, 2.2));
      const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
      keyLight.position.set(12, 18, 8);
      scene.add(keyLight);

      const floorMaterial = new THREE.MeshStandardMaterial({
        color: 0xdbeafe,
        metalness: 0,
        opacity: 0.58,
        roughness: 0.9,
        transparent: true,
      });
      const beamMaterial = new THREE.MeshStandardMaterial({
        color: 0x2563eb,
        roughness: 0.55,
      });
      const columnMaterial = new THREE.MeshStandardMaterial({
        color: 0x64748b,
        roughness: 0.65,
      });
      const selectedMaterial = new THREE.MeshStandardMaterial({
        color: 0xdc2626,
        roughness: 0.5,
      });

      const scale = 0.00038;
      const extentX = 49200;
      const extentY = 41700;
      for (const [index, floor] of project.floors.entries()) {
        const y = floor.elevationM === null ? index * 1.6 : floor.elevationM * 0.42;
        const slab = new THREE.Mesh(new THREE.BoxGeometry(18.7, 0.08, 15.8), floorMaterial);
        slab.position.set(0, y, 0);
        group.add(slab);
      }

      for (const object of objects) {
        const floorIndex = Math.max(
          0,
          project.floors.findIndex((floor) => floor.id === object.floorId),
        );
        const floor = project.floors[floorIndex];
        const baseY =
          floor?.elevationM === null || floor?.elevationM === undefined
            ? floorIndex * 1.6
            : floor.elevationM * 0.42;

        if (object.type === "beam") {
          const [[x1, y1], [x2, y2]] = object.lineMm;
          const length = Math.hypot(x2 - x1, y2 - y1) * scale;
          const beam = new THREE.Mesh(
            new THREE.BoxGeometry(length, 0.18, 0.24),
            object.floorId === selectedFloorId ? beamMaterial : selectedMaterial,
          );
          beam.position.set(
            ((x1 + x2) / 2 - extentX / 2) * scale,
            baseY + 0.35,
            ((y1 + y2) / 2 - extentY / 2) * scale,
          );
          beam.rotation.y = -Math.atan2(y2 - y1, x2 - x1);
          group.add(beam);
        }

        if (object.type === "column") {
          const column = new THREE.Mesh(
            new THREE.BoxGeometry(0.28, 1.2, 0.28),
            columnMaterial,
          );
          column.position.set(
            (object.coordMm[0] - extentX / 2) * scale,
            baseY + 0.65,
            (object.coordMm[1] - extentY / 2) * scale,
          );
          group.add(column);
        }
      }

      function resize() {
        if (!canvas.parentElement || !renderer) return;
        const width = Math.max(320, canvas.parentElement.clientWidth);
        const height = Math.max(260, canvas.parentElement.clientHeight);
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
      }

      function animate() {
        if (!renderer) return;
        group.rotation.y = -0.42 + Math.sin(Date.now() / 2400) * 0.04;
        resize();
        renderer.render(scene, camera);
        animationFrame = window.requestAnimationFrame(animate);
      }

      resize();
      animate();
    });

    return () => {
      disposed = true;
      window.cancelAnimationFrame(animationFrame);
      renderer?.dispose();
    };
  }, [objects, project, selectedFloorId]);

  return (
    <section className="rounded-lg border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="inline-flex items-center gap-2 text-sm font-medium">
          <Box className="size-4 text-violet-600" />
          ThreeDPreviewPanel
        </div>
        {notice && (
          <span className="inline-flex items-center gap-1 text-xs text-amber-700">
            <AlertTriangle className="size-3.5" />
            {notice}
          </span>
        )}
      </div>
      <div className="h-[300px] bg-gradient-to-b from-zinc-50 to-white">
        <canvas ref={canvasRef} className="h-full w-full" data-testid="read-agent-3d-canvas" />
      </div>
    </section>
  );
}

function JsonLivePanel({
  activeTab,
  onTabChange,
  patch,
  state,
}: {
  activeTab: "stage" | "view" | "patch" | "audit";
  onTabChange: (tab: "stage" | "view" | "patch" | "audit") => void;
  patch: unknown;
  state: ReturnType<typeof createInitialReadAgentState>;
}) {
  const payload =
    activeTab === "stage"
      ? state.stageJson
      : activeTab === "view"
        ? state.viewModelJson
        : activeTab === "patch"
          ? patch
          : state.auditLog;

  return (
    <section className="rounded-lg border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="inline-flex items-center gap-2 text-sm font-medium">
          <FileJson className="size-4 text-blue-600" />
          JSON / Diff / Audit
        </div>
        <div className="inline-flex overflow-hidden rounded-md border border-zinc-300">
          {(["stage", "view", "patch", "audit"] as const).map((tab) => (
            <button
              className={cx(
                "px-2 py-1 text-xs",
                activeTab === tab ? "bg-zinc-900 text-white" : "bg-white text-zinc-700",
              )}
              key={tab}
              onClick={() => onTabChange(tab)}
              type="button"
            >
              {tab}
            </button>
          ))}
        </div>
      </div>
      <pre className="h-[300px] overflow-auto p-3 text-xs leading-relaxed text-zinc-700">
        {formatJson(payload)}
      </pre>
    </section>
  );
}

function InspectorPanel({
  draft,
  mode,
  onCommit,
  onDraftChange,
  onOcr,
  onRedo,
  onUndo,
  preview,
  redoDisabled,
  selectedObject,
  undoDisabled,
}: {
  draft: {
    label: string;
    section: string;
    reviewStatus: ReviewStatus;
  };
  mode: "processing" | "edit";
  onCommit: () => void;
  onDraftChange: (draft: {
    label: string;
    section: string;
    reviewStatus: ReviewStatus;
  }) => void;
  onOcr: () => void;
  onRedo: () => void;
  onUndo: () => void;
  preview: ReturnType<typeof createOperationPreview> | null;
  redoDisabled: boolean;
  selectedObject?: SemanticObject;
  undoDisabled: boolean;
}) {
  const lowConfidence =
    selectedObject?.confidence !== undefined && selectedObject.confidence < 0.9;

  return (
    <aside className="space-y-4">
      <section className="rounded-lg border border-zinc-200 bg-white">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <div className="inline-flex items-center gap-2 text-sm font-medium">
            <Pencil className="size-4 text-blue-600" />
            InspectorEvidencePanel
          </div>
          <span className="text-xs text-zinc-500">{mode}</span>
        </div>
        <div className="space-y-3 p-3">
          {selectedObject ? (
            <>
              <div className="flex items-center justify-between gap-2">
                <div>
                  <div className="font-medium">{selectedObject.label}</div>
                  <div className="text-xs text-zinc-500">{selectedObject.id}</div>
                </div>
                <span
                  className={cx(
                    "rounded-md border px-2 py-1 text-xs",
                    statusClass(selectedObject.reviewStatus),
                  )}
                >
                  {selectedObject.reviewStatus}
                </span>
              </div>

              {lowConfidence && (
                <div className="inline-flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-sm text-amber-800">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  confidence {selectedObject.confidence.toFixed(2)}
                </div>
              )}

              {selectedObject.type === "beam" && (
                <BeamForm draft={draft} onDraftChange={onDraftChange} />
              )}

              <div className="grid grid-cols-2 gap-2">
                <button
                  className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-zinc-300 bg-white text-sm hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={undoDisabled}
                  onClick={onUndo}
                  type="button"
                >
                  <Undo2 className="size-4" />
                  Undo
                </button>
                <button
                  className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-zinc-300 bg-white text-sm hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={redoDisabled}
                  onClick={onRedo}
                  type="button"
                >
                  <Redo2 className="size-4" />
                  Redo
                </button>
              </div>

              <button
                className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md border border-blue-200 bg-blue-50 text-sm text-blue-700 hover:bg-blue-100"
                disabled={!selectedObject.evidenceRef}
                onClick={onOcr}
                type="button"
              >
                <Search className="size-4" />
                OCR region
              </button>
            </>
          ) : (
            <div className="text-sm text-zinc-500">No object selected</div>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-zinc-200 bg-white">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <div className="inline-flex items-center gap-2 text-sm font-medium">
            <GitBranch className="size-4 text-emerald-600" />
            Operation Preview
          </div>
          {preview?.validation.ok ? (
            <CheckCircle2 className="size-4 text-emerald-600" />
          ) : (
            <AlertTriangle className="size-4 text-amber-600" />
          )}
        </div>
        <div className="space-y-3 p-3">
          <pre className="max-h-[220px] overflow-auto rounded-md bg-zinc-950 p-3 text-xs text-zinc-100">
            {formatJson({
              operation: preview?.operation,
              json_patch: preview?.jsonPatch,
              validation: preview?.validation,
              audit_event: preview?.auditEvent
                ? {
                    actor: preview.auditEvent.actor,
                    objectId: preview.auditEvent.objectId,
                    patch: preview.auditEvent.patch,
                  }
                : null,
            })}
          </pre>
          {preview && !preview.validation.ok && (
            <ul className="space-y-1 text-sm text-red-700">
              {preview.validation.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
          <button
            className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md bg-zinc-900 px-3 text-sm text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-300"
            disabled={!preview?.validation.ok}
            onClick={onCommit}
            type="button"
          >
            <CheckCircle2 className="size-4" />
            Commit
          </button>
        </div>
      </section>
    </aside>
  );
}

function BeamForm({
  draft,
  onDraftChange,
}: {
  draft: {
    label: string;
    section: string;
    reviewStatus: ReviewStatus;
  };
  onDraftChange: (draft: {
    label: string;
    section: string;
    reviewStatus: ReviewStatus;
  }) => void;
}) {
  return (
    <div className="grid gap-3">
      <label className="grid gap-1 text-sm">
        <span className="text-zinc-600">梁号</span>
        <input
          className="h-9 rounded-md border border-zinc-300 px-3"
          value={draft.label}
          onChange={(event) =>
            onDraftChange({ ...draft, label: event.target.value })
          }
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="text-zinc-600">截面</span>
        <input
          className="h-9 rounded-md border border-zinc-300 px-3"
          value={draft.section}
          onChange={(event) =>
            onDraftChange({ ...draft, section: event.target.value })
          }
        />
      </label>
      <label className="grid gap-1 text-sm">
        <span className="text-zinc-600">review_status</span>
        <select
          className="h-9 rounded-md border border-zinc-300 bg-white px-3"
          value={draft.reviewStatus}
          onChange={(event) =>
            onDraftChange({
              ...draft,
              reviewStatus: event.target.value as ReviewStatus,
            })
          }
        >
          <option value="candidate">candidate</option>
          <option value="needs_review">needs_review</option>
          <option value="accepted">accepted</option>
          <option value="rejected">rejected</option>
        </select>
      </label>
    </div>
  );
}

function AuditPanel({
  state,
}: {
  state: ReturnType<typeof createInitialReadAgentState>;
}) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="inline-flex items-center gap-2 text-sm font-medium">
          <GitBranch className="size-4 text-emerald-600" />
          BottomAuditPanel
        </div>
        <span className="text-xs text-zinc-500">{state.auditLog.length} events</span>
      </div>
      <div className="grid gap-3 p-3 md:grid-cols-2 xl:grid-cols-3">
        {state.auditLog.length === 0 ? (
          <div className="text-sm text-zinc-500">No committed operations</div>
        ) : (
          state.auditLog.map((event) => (
            <article className="rounded-md border border-zinc-200 p-3" key={event.id}>
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="font-medium">{event.objectId}</span>
                <span className="text-xs text-zinc-500">{event.actor}</span>
              </div>
              <div className="text-xs text-zinc-500">{event.ts}</div>
              <pre className="mt-2 max-h-28 overflow-auto rounded-md bg-zinc-100 p-2 text-xs">
                {formatJson(event.patch)}
              </pre>
            </article>
          ))
        )}
      </div>
    </section>
  );
}

function ContractPanel() {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white">
      <div className="flex items-center gap-2 border-b px-3 py-2 text-sm font-medium">
        <CheckCircle2 className="size-4 text-emerald-600" />
        Acceptance Map
      </div>
      <div className="max-h-[300px] overflow-auto p-3">
        <div className="space-y-2">
          {ACCEPTANCE_MATRIX.map((item) => (
            <details className="rounded-md border border-zinc-200 p-2" key={item.docSection}>
              <summary className="cursor-pointer text-sm font-medium">
                {item.docSection}
              </summary>
              <p className="mt-2 text-sm text-zinc-600">{item.requirement}</p>
              <div className="mt-2 text-xs text-zinc-500">
                {item.implementedBy.join(" · ")}
              </div>
            </details>
          ))}
        </div>
        <div className="mt-3 border-t pt-3">
          <div className="mb-2 text-xs font-medium uppercase text-zinc-500">
            REST endpoints
          </div>
          <ul className="space-y-1 text-xs text-zinc-600">
            {REST_ENDPOINTS.map((endpoint) => (
              <li key={endpoint}>{endpoint}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
