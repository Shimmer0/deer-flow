from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from .schemas import BlueprintRecord, BuildingRecord, FloorRecord, ProjectRecord, RunEvent, RunRecord

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_ALLOWED_ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".pdf",
    ".json",
    ".jsonl",
    ".txt",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def safe_id(value: str, *, name: str = "id") -> str:
    if not _SAFE_ID_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name}: {value!r}")
    return value


def safe_filename(name: str) -> str:
    base = Path(name).name.strip() or "upload"
    base = _SAFE_FILE_RE.sub("_", base)
    return base[:180]


def read_agent_data_root() -> Path:
    configured = os.environ.get("READ_AGENT_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    # When uvicorn is started from deer-flow/backend, this becomes backend/data/read-agent.
    return (Path.cwd() / "data" / "read-agent").resolve()


class ReadAgentStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else read_agent_data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "projects").mkdir(exist_ok=True)
        (self.root / "runs").mkdir(exist_ok=True)

    # ---------- generic JSON helpers ----------
    def _atomic_write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)

    def write_json(self, path: Path, value: Any) -> None:
        self._atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False))

    def read_json(self, path: Path, *, default: Any | None = None) -> Any:
        if not path.is_file():
            if default is not None:
                return default
            raise HTTPException(status_code=404, detail=f"JSON artifact not found: {self.asset_ref(path)}")
        return json.loads(path.read_text(encoding="utf-8"))

    def asset_ref(self, path: Path) -> str:
        resolved = path.resolve()
        resolved.relative_to(self.root)
        return resolved.relative_to(self.root).as_posix()

    def resolve_asset(self, asset_ref: str) -> Path:
        if not asset_ref or "\x00" in asset_ref:
            raise HTTPException(status_code=400, detail="Invalid asset path")
        parts = Path(asset_ref).parts
        if any(part in {"", ".", ".."} for part in parts):
            raise HTTPException(status_code=400, detail="Invalid asset path")
        candidate = (self.root / Path(*parts)).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Asset path escapes data root") from error
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail=f"Asset not found: {asset_ref}")
        if candidate.suffix.lower() not in _ALLOWED_ASSET_EXTENSIONS:
            raise HTTPException(status_code=403, detail="Asset type is not exposed by read-agent")
        return candidate

    # ---------- project helpers ----------
    def project_dir(self, project_id: str) -> Path:
        return self.root / "projects" / safe_id(project_id, name="project_id")

    def project_json_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "project.json"

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        for path in sorted((self.root / "projects").glob("*/project.json")):
            project = self.read_json(path)
            projects.append(self.project_summary(project))
        return projects

    def project_summary(self, project: dict[str, Any]) -> dict[str, Any]:
        floors: list[str] = []
        blueprints: list[str] = []
        for _building, floor, blueprint in self.iter_floor_blueprints(project):
            if floor["floor_id"] not in floors:
                floors.append(floor["floor_id"])
            if blueprint["blueprint_id"] not in blueprints:
                blueprints.append(blueprint["blueprint_id"])
        return {
            "project_id": project["project_id"],
            "name": project.get("name"),
            "discipline": project.get("discipline"),
            "floor_ids": floors,
            "blueprint_ids": blueprints,
            "updated_at": project.get("updated_at"),
        }

    def create_project(self, *, name: str, discipline: str, building_id: str, building_name: str) -> dict[str, Any]:
        now = utc_now()
        project_id = make_id("proj")
        project = ProjectRecord(
            project_id=project_id,
            name=name,
            discipline=discipline,
            buildings=[BuildingRecord(building_id=building_id, building_name=building_name, floors=[])],
            created_at=now,
            updated_at=now,
        ).model_dump(mode="json")
        self.save_project(project)
        return project

    def load_project(self, project_id: str) -> dict[str, Any]:
        return self.read_json(self.project_json_path(project_id))

    def save_project(self, project: dict[str, Any]) -> None:
        project["updated_at"] = utc_now()
        self.write_json(self.project_json_path(project["project_id"]), project)

    def iter_floor_blueprints(self, project: dict[str, Any]) -> Iterable[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
        for building in project.get("buildings", []):
            for floor in building.get("floors", []):
                for blueprint in floor.get("blueprints", []):
                    yield building, floor, blueprint

    def find_blueprint(self, project: dict[str, Any], blueprint_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        safe_id(blueprint_id, name="blueprint_id")
        for building, floor, blueprint in self.iter_floor_blueprints(project):
            if blueprint.get("blueprint_id") == blueprint_id:
                return building, floor, blueprint
        raise HTTPException(status_code=404, detail=f"Unknown blueprint_id: {blueprint_id}")

    def find_floor(self, project: dict[str, Any], floor_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        safe_id(floor_id, name="floor_id")
        for building in project.get("buildings", []):
            for floor in building.get("floors", []):
                if floor.get("floor_id") == floor_id:
                    return building, floor
        raise HTTPException(status_code=404, detail=f"Unknown floor_id: {floor_id}")

    def ensure_floor(
        self,
        project: dict[str, Any],
        *,
        building_id: str,
        building_name: str,
        floor_id: str,
        floor_name: str,
        floor_index: int,
        elevation_m: float | None = None,
        floor_height_m: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        safe_id(building_id, name="building_id")
        safe_id(floor_id, name="floor_id")
        building = next((b for b in project.get("buildings", []) if b.get("building_id") == building_id), None)
        if building is None:
            building = {"building_id": building_id, "building_name": building_name, "floors": []}
            project.setdefault("buildings", []).append(building)
        floor = next((f for f in building.get("floors", []) if f.get("floor_id") == floor_id), None)
        if floor is None:
            floor = FloorRecord(
                floor_id=floor_id,
                floor_name=floor_name,
                floor_index=floor_index,
                elevation_m=elevation_m,
                floor_height_m=floor_height_m,
                blueprints=[],
            ).model_dump(mode="json")
            building.setdefault("floors", []).append(floor)
        return building, floor

    async def add_uploaded_blueprint(
        self,
        *,
        project_id: str,
        file: UploadFile,
        building_id: str,
        building_name: str,
        floor_id: str,
        floor_name: str,
        floor_index: int,
        drawing_type: str,
        title: str | None = None,
        elevation_m: float | None = None,
        floor_height_m: float | None = None,
    ) -> dict[str, Any]:
        project = self.load_project(project_id)
        _building, floor = self.ensure_floor(
            project,
            building_id=building_id,
            building_name=building_name,
            floor_id=floor_id,
            floor_name=floor_name,
            floor_index=floor_index,
            elevation_m=elevation_m,
            floor_height_m=floor_height_m,
        )
        blueprint_id = make_id("bp")
        clean_name = safe_filename(file.filename or f"{blueprint_id}.png")
        dest = self.project_dir(project_id) / "blueprints" / blueprint_id / "original" / clean_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                output.write(chunk)

        now = utc_now()
        record = BlueprintRecord(
            blueprint_id=blueprint_id,
            title=title or Path(clean_name).stem,
            drawing_type=drawing_type,
            file_name=clean_name,
            mime_type=file.content_type,
            asset_ref=self.asset_ref(dest),
            status="uploaded",
            floor_id=floor_id,
            building_id=building_id,
            created_at=now,
            updated_at=now,
            metadata={"original_size_bytes": dest.stat().st_size},
        ).model_dump(mode="json")
        floor.setdefault("blueprints", []).append(record)
        self.save_project(project)
        return record

    # ---------- run helpers ----------
    def run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / safe_id(run_id, name="run_id")

    def run_json_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.json"

    def events_jsonl_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def create_run(self, *, project_id: str, blueprint_ids: list[str], floor_ids: list[str], target_stages: list[str]) -> dict[str, Any]:
        now = utc_now()
        run_id = make_id("run")
        run = RunRecord(
            run_id=run_id,
            project_id=project_id,
            blueprint_ids=blueprint_ids,
            floor_ids=floor_ids,
            target_stages=target_stages,
            status="queued",
            created_at=now,
            updated_at=now,
            events_url=f"/api/read-agent/runs/{run_id}/events",
        ).model_dump(mode="json")
        self.save_run(run)
        self.events_jsonl_path(run_id).write_text("", encoding="utf-8")
        return run

    def load_run(self, run_id: str) -> dict[str, Any]:
        return self.read_json(self.run_json_path(run_id))

    def save_run(self, run: dict[str, Any]) -> None:
        run["updated_at"] = utc_now()
        self.write_json(self.run_json_path(run["run_id"]), run)

    def update_run_status(self, run_id: str, status: str, *, error: str | None = None, edit_base_version: str | None = None, artifact_refs: dict[str, Any] | None = None) -> dict[str, Any]:
        run = self.load_run(run_id)
        run["status"] = status
        if error is not None:
            run["error"] = error
        if edit_base_version is not None:
            run["edit_base_version"] = edit_base_version
        if artifact_refs:
            run.setdefault("artifact_refs", {}).update(artifact_refs)
        self.save_run(run)
        return run

    def append_event(self, run_id: str, event: dict[str, Any]) -> dict[str, Any]:
        path = self.events_jsonl_path(run_id)
        existing_count = 0
        if path.exists():
            existing_count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        payload = RunEvent(seq=existing_count + 1, sseType=event.get("event_type"), ts=utc_now(), **event).model_dump(mode="json")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        return payload

    def read_events(self, run_id: str, *, after_seq: int = 0) -> list[dict[str, Any]]:
        path = self.events_jsonl_path(run_id)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if int(event.get("seq", 0)) > after_seq:
                events.append(event)
        return events

    # ---------- output paths ----------
    def outputs_dir(self, project_id: str, floor_id: str) -> Path:
        return self.project_dir(project_id) / "outputs" / safe_id(floor_id, name="floor_id")

    def versions_dir(self, project_id: str, floor_id: str) -> Path:
        return self.outputs_dir(project_id, floor_id) / "versions"

    def write_output_json(self, project_id: str, floor_id: str, relative: str, value: Any) -> str:
        path = self.outputs_dir(project_id, floor_id) / relative
        self.write_json(path, value)
        return self.asset_ref(path)

    def load_output_json_by_ref(self, asset_ref: str) -> Any:
        return self.read_json(self.resolve_asset(asset_ref))

    def copy_asset_to_public_outputs(self, src: Path, project_id: str, floor_id: str, relative: str) -> str:
        dest = self.outputs_dir(project_id, floor_id) / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return self.asset_ref(dest)
