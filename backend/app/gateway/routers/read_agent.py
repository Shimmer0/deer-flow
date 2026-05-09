from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.read_agent.operations import build_operation_preview, commit_operation
from app.read_agent.recognition_pipeline import _maybe_ocr, run_read_agent_pipeline
from app.read_agent.schemas import CommitOperationRequest, CreateProjectRequest, CreateRunRequest, OcrRegionRequest, PreviewOperationRequest
from app.read_agent.storage import ReadAgentStore

router = APIRouter(prefix="/api/read-agent", tags=["read-agent"])

_DONE_STATUSES = {"ready_for_edit", "failed", "cancelled"}


def _store() -> ReadAgentStore:
    return ReadAgentStore()


@router.get("/health", response_model=dict)
async def health() -> dict[str, Any]:
    store = _store()
    return {"ok": True, "data_root": str(store.root), "mode": "real_runtime"}


@router.post("/projects", response_model=dict)
async def create_project(body: CreateProjectRequest) -> dict[str, Any]:
    project = _store().create_project(
        name=body.name,
        discipline=body.discipline,
        building_id=body.building_id,
        building_name=body.building_name,
    )
    return {"project": project}


@router.get("/projects", response_model=dict)
async def list_projects() -> dict[str, Any]:
    return {"projects": _store().list_projects()}


@router.get("/projects/{project_id}", response_model=dict)
async def get_project(project_id: str) -> dict[str, Any]:
    return _store().load_project(project_id)


@router.post("/projects/{project_id}/blueprints", response_model=dict)
async def upload_blueprints(
    project_id: str,
    files: list[UploadFile] = File(...),
    building_id: str = Form("B01"),
    building_name: str = Form("主楼"),
    floor_id: str = Form(...),
    floor_name: str = Form(...),
    floor_index: int = Form(0),
    drawing_type: str = Form("structural_plan"),
    elevation_m: float | None = Form(None),
    floor_height_m: float | None = Form(None),
) -> dict[str, Any]:
    store = _store()
    uploaded: list[dict[str, Any]] = []
    for file in files:
        uploaded.append(
            await store.add_uploaded_blueprint(
                project_id=project_id,
                file=file,
                building_id=building_id,
                building_name=building_name,
                floor_id=floor_id,
                floor_name=floor_name,
                floor_index=floor_index,
                drawing_type=drawing_type,
                elevation_m=elevation_m,
                floor_height_m=floor_height_m,
            )
        )
    return {"project": store.load_project(project_id), "blueprints": uploaded}


@router.get("/projects/{project_id}/blueprints/{blueprint_id}", response_model=dict)
async def get_blueprint(project_id: str, blueprint_id: str) -> dict[str, Any]:
    store = _store()
    project = store.load_project(project_id)
    building, floor, blueprint = store.find_blueprint(project, blueprint_id)
    return {**blueprint, "project_id": project_id, "building_id": building["building_id"], "floor_id": floor["floor_id"], "floor_name": floor.get("floor_name")}


@router.get("/projects/{project_id}/floors/{floor_id}/view-model", response_model=dict)
async def get_floor_view_model(project_id: str, floor_id: str) -> dict[str, Any]:
    store = _store()
    project = store.load_project(project_id)
    _building, floor = store.find_floor(project, floor_id)
    ref = floor.get("current_view_model_asset")
    if not ref:
        return {
            "schema_version": "cv-notfunning/semantic-view-model/v1.0",
            "project_id": project_id,
            "floor_id": floor_id,
            "base_json_version": None,
            "objects": [],
            "layers": [],
            "quality": {"recognition_status": "not_processed", "object_count": 0},
            "message": "Run /api/read-agent/runs before entering edit mode.",
        }
    return store.load_output_json_by_ref(ref)


@router.get("/projects/{project_id}/floors/{floor_id}/semantic-json", response_model=dict)
async def get_floor_semantic_json(project_id: str, floor_id: str) -> dict[str, Any]:
    store = _store()
    project = store.load_project(project_id)
    _building, floor = store.find_floor(project, floor_id)
    ref = floor.get("current_semantic_version")
    if not ref:
        raise HTTPException(status_code=404, detail="Floor has no semantic JSON yet")
    return store.load_output_json_by_ref(ref)


@router.post("/runs", response_model=dict)
async def create_agent_run(body: CreateRunRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    store = _store()
    project = store.load_project(body.project_id)
    selected_blueprints: list[str] = []
    selected_floors: list[str] = []
    for _building, floor, blueprint in store.iter_floor_blueprints(project):
        if body.blueprint_ids and blueprint["blueprint_id"] not in body.blueprint_ids:
            continue
        if body.floor_ids and floor["floor_id"] not in body.floor_ids:
            continue
        selected_blueprints.append(blueprint["blueprint_id"])
        if floor["floor_id"] not in selected_floors:
            selected_floors.append(floor["floor_id"])
    if not selected_blueprints:
        raise HTTPException(status_code=400, detail="No uploaded blueprints match the requested floor_ids/blueprint_ids")
    run = store.create_run(project_id=body.project_id, blueprint_ids=selected_blueprints, floor_ids=selected_floors, target_stages=list(body.target_stages))
    background_tasks.add_task(run_read_agent_pipeline, str(store.root), run["run_id"])
    return run


@router.get("/runs/{run_id}", response_model=dict)
async def get_agent_run(run_id: str) -> dict[str, Any]:
    return _store().load_run(run_id)


def _format_sse(event: dict[str, Any]) -> str:
    event_name = event.get("event_type") or event.get("sseType") or "message"
    return f"event: {event_name}\ndata: {json.dumps(event, ensure_ascii=False, sort_keys=True)}\n\n"


async def _event_stream(store: ReadAgentStore, run_id: str) -> Iterable[str]:
    last_seq = 0
    while True:
        events = store.read_events(run_id, after_seq=last_seq)
        for event in events:
            last_seq = max(last_seq, int(event.get("seq", 0)))
            yield _format_sse(event)
        run = store.load_run(run_id)
        if run.get("status") in _DONE_STATUSES and not events:
            yield _format_sse(
                {
                    "seq": last_seq + 1,
                    "event_type": "stream.closed",
                    "sseType": "stream.closed",
                    "run_id": run_id,
                    "project_id": run["project_id"],
                    "title": "事件流结束",
                    "ts": run.get("updated_at"),
                    "payload": {"status": run.get("status")},
                }
            )
            break
        await asyncio.sleep(0.5)


@router.get("/runs/{run_id}/events")
async def stream_agent_run_events(run_id: str) -> StreamingResponse:
    store = _store()
    store.load_run(run_id)
    return StreamingResponse(_event_stream(store, run_id), media_type="text/event-stream")


@router.get("/assets/{asset_path:path}")
async def get_asset(asset_path: str) -> FileResponse:
    path = _store().resolve_asset(asset_path)
    return FileResponse(path)


@router.post("/editor/operations/preview", response_model=dict)
async def preview_operation(body: PreviewOperationRequest) -> dict[str, Any]:
    return build_operation_preview(_store(), body.model_dump(mode="json"))


@router.post("/editor/operations/commit", response_model=dict)
async def commit_editor_operation(body: CommitOperationRequest) -> dict[str, Any]:
    return commit_operation(_store(), body.model_dump(mode="json"))


@router.post("/editor/ocr-region", response_model=dict)
async def ocr_region(body: OcrRegionRequest) -> dict[str, Any]:
    store = _store()
    project = store.load_project(body.project_id)
    _building, _floor, blueprint = store.find_blueprint(project, body.blueprint_id)
    image_ref = body.image_ref or blueprint["asset_ref"]
    image_path = store.resolve_asset(image_ref)
    result = _maybe_ocr(image_path, bbox=body.bbox)
    return {
        "project_id": body.project_id,
        "blueprint_id": body.blueprint_id,
        "image_ref": image_ref,
        "bbox": body.bbox,
        "bbox_space": body.bbox_space,
        "hint": body.hint,
        "ocr_result": result,
        "candidates": [{"text": unit.get("text"), "confidence": unit.get("confidence"), "bbox": unit.get("bbox")} for unit in (result or {}).get("text_units", [])],
        "auto_commit": False,
    }


@router.post("/editor/validate", response_model=dict)
async def validate_current_floor(body: dict[str, Any]) -> dict[str, Any]:
    project_id = body.get("project_id")
    floor_id = body.get("floor_id")
    if not project_id or not floor_id:
        raise HTTPException(status_code=400, detail="project_id and floor_id are required")
    view_model = await get_floor_view_model(project_id, floor_id)
    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not view_model.get("objects"):
        warnings.append({"code": "no_objects", "message": "No semantic objects are available for this floor."})
    for obj in view_model.get("objects", []):
        if obj.get("object_type") in {"main_beam", "column"} and not obj.get("evidence_refs") and obj.get("review_status") in {"accepted", "human_confirmed"}:
            warnings.append({"code": "accepted_without_evidence", "object_id": obj.get("semantic_object_id")})
    return {
        "project_id": project_id,
        "floor_id": floor_id,
        "validation_result": {
            "status": "failed" if errors else ("review_required" if warnings else "passed"),
            "rules": ["view_model_loaded", "accepted_objects_should_have_evidence"],
            "errors": errors,
            "warnings": warnings,
        },
    }
