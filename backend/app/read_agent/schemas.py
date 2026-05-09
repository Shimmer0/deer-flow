from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

READ_AGENT_SCHEMA_VERSION = "cv-notfunning/read-agent-runtime/v1.0"


class Section(BaseModel):
    width_mm: int = Field(gt=0)
    height_mm: int = Field(gt=0)


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    discipline: str = Field(default="structure", max_length=80)
    building_id: str = Field(default="B01", min_length=1, max_length=80)
    building_name: str = Field(default="主楼", max_length=120)


class BlueprintRecord(BaseModel):
    blueprint_id: str
    title: str
    drawing_type: str = "structural_plan"
    file_name: str
    mime_type: str | None = None
    asset_ref: str
    status: Literal["uploaded", "processing", "ready_for_edit", "failed"] = "uploaded"
    floor_id: str
    building_id: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FloorRecord(BaseModel):
    floor_id: str
    floor_name: str
    floor_index: int = 0
    elevation_m: float | None = None
    floor_height_m: float | None = None
    blueprints: list[BlueprintRecord] = Field(default_factory=list)
    current_semantic_version: str | None = None
    current_view_model_asset: str | None = None


class BuildingRecord(BaseModel):
    building_id: str
    building_name: str
    floors: list[FloorRecord] = Field(default_factory=list)


class ProjectRecord(BaseModel):
    schema_version: str = READ_AGENT_SCHEMA_VERSION
    project_id: str
    name: str
    discipline: str = "structure"
    buildings: list[BuildingRecord] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CreateRunRequest(BaseModel):
    project_id: str
    blueprint_ids: list[str] | None = None
    floor_ids: list[str] | None = None
    target_stages: list[Literal["stage1", "stage2", "stage3"]] = Field(default_factory=lambda: ["stage1", "stage2", "stage3"])
    force_reprocess: bool = False
    llm_enabled: bool = True
    ocr_enabled: bool = True


class RunRecord(BaseModel):
    run_id: str
    project_id: str
    blueprint_ids: list[str]
    floor_ids: list[str]
    target_stages: list[str]
    status: Literal["queued", "running", "ready_for_edit", "failed", "cancelled"] = "queued"
    created_at: str
    updated_at: str
    edit_base_version: str | None = None
    events_url: str | None = None
    error: str | None = None
    artifact_refs: dict[str, Any] = Field(default_factory=dict)


class RunEvent(BaseModel):
    seq: int
    run_id: str
    event_type: str
    sseType: str | None = None
    project_id: str
    floor_id: str | None = None
    blueprint_id: str | None = None
    stage: str | None = None
    title: str
    summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    ts: str


class OperationTarget(BaseModel):
    object_id: str
    object_type: Literal["main_beam", "column", "axis", "label", "dimension_chain", "secondary_beam_candidate", "opening_candidate"]


class EditorOperation(BaseModel):
    operation_id: str
    operation_type: Literal[
        "update_beam_section",
        "update_beam_label",
        "update_review_status",
        "update_column_section",
        "reject_object",
        "accept_object",
    ]
    actor: dict[str, Any] = Field(default_factory=lambda: {"type": "human", "id": "web-ui-user"})
    target: OperationTarget
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("operation_id")
    @classmethod
    def operation_id_safe(cls, value: str) -> str:
        if not value or len(value) > 120:
            raise ValueError("operation_id must be 1..120 chars")
        return value


class PreviewOperationRequest(BaseModel):
    project_id: str
    floor_id: str
    blueprint_id: str | None = None
    base_json_version: str | None = None
    operation: EditorOperation


class CommitOperationRequest(PreviewOperationRequest):
    preview_result_id: str | None = None
    user_confirmation: bool = False


class OcrRegionRequest(BaseModel):
    project_id: str
    blueprint_id: str
    image_ref: str | None = None
    bbox: list[float] = Field(min_length=4, max_length=4)
    bbox_space: Literal["image_px", "model_mm", "viewport_px"] = "image_px"
    hint: str | None = None


class ValidationResult(BaseModel):
    status: Literal["passed", "failed", "review_required"]
    rules: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
