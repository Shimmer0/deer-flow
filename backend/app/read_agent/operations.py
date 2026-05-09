from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from .schemas import EditorOperation
from .storage import ReadAgentStore, make_id
from .view_model import compile_semantic_view_model

_SECTION_TEXT_RE = re.compile(r"(?P<w>\d{2,5})\s*[xX×]\s*(?P<h>\d{2,5})")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _unwrap(semantic_json: dict[str, Any]) -> dict[str, Any]:
    if "stage2_primary_structure_result" in semantic_json:
        return semantic_json["stage2_primary_structure_result"]
    if "stage2" in semantic_json:
        stage2 = semantic_json["stage2"]
        return stage2.get("stage2_primary_structure_result") or stage2
    return semantic_json


def _parse_section(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        width = value.get("width_mm") or value.get("b") or value.get("width")
        height = value.get("height_mm") or value.get("h") or value.get("height")
        if width is not None and height is not None:
            return {"width_mm": int(width), "height_mm": int(height)}
    if isinstance(value, str):
        match = _SECTION_TEXT_RE.search(value)
        if match:
            return {"width_mm": int(match.group("w")), "height_mm": int(match.group("h"))}
    raise HTTPException(status_code=422, detail="section must be {width_mm,height_mm} or text like 600x1200")


def _latest_semantic_ref(project: dict[str, Any], floor_id: str) -> str:
    for building in project.get("buildings", []):
        for floor in building.get("floors", []):
            if floor.get("floor_id") == floor_id:
                version = floor.get("current_semantic_version")
                if not version:
                    raise HTTPException(status_code=409, detail="Floor has no recognized semantic JSON yet. Run read-agent first.")
                return version
    raise HTTPException(status_code=404, detail=f"Unknown floor_id: {floor_id}")


def _find_object(stage2_payload: dict[str, Any], object_id: str, object_type: str) -> tuple[list[Any], dict[str, Any], str]:
    candidates: list[str]
    if object_type == "main_beam":
        candidates = ["main_beams", "beams"]
    elif object_type == "column":
        candidates = ["columns", "column_grid"]
    else:
        candidates = ["main_beams", "beams", "columns", "column_grid"]
    for key in candidates:
        values = stage2_payload.get(key) or []
        if not isinstance(values, list):
            continue
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            ids = [item.get("object_id"), item.get("id"), item.get("beam_id"), item.get("column_id")]
            if object_id in [str(v) for v in ids if v is not None]:
                return [key, index], item, key
    raise HTTPException(status_code=404, detail=f"Object not found in semantic JSON: {object_id}")


def _json_pointer(path: list[Any]) -> str:
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in path)


def _set_by_path(doc: dict[str, Any], path: list[Any], value: Any) -> None:
    target: Any = doc
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


def _validate_operation(stage2_payload: dict[str, Any], operation: EditorOperation, target_object: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rules = ["object_exists"]

    if operation.target.object_type == "main_beam":
        rules.extend(["beam_section_valid", "main_beam_endpoints_present_when_declared"])
        start = target_object.get("start_node") or target_object.get("start_grid_node")
        end = target_object.get("end_node") or target_object.get("end_grid_node")
        if (start is None) != (end is None):
            errors.append({"code": "beam_endpoint_partial", "message": "main beam has only one endpoint"})
        if operation.operation_type == "update_beam_section":
            section = _parse_section(operation.params.get("section"))
            if section["width_mm"] <= 0 or section["height_mm"] <= 0:
                errors.append({"code": "section_non_positive", "message": "beam section dimensions must be positive"})
    if operation.target.object_type == "column" and operation.operation_type == "update_column_section":
        rules.append("column_section_valid")
        _parse_section(operation.params.get("section"))
    if operation.operation_type in {"accept_object", "update_review_status"}:
        status = operation.params.get("review_status") or "accepted"
        if status in {"accepted", "human_confirmed"} and not target_object.get("evidence_refs"):
            warnings.append({"code": "accepted_without_evidence", "message": "object has no evidence_refs; keep audit log and consider adding evidence"})

    return {"status": "failed" if errors else ("review_required" if warnings else "passed"), "rules": rules, "errors": errors, "warnings": warnings}


def build_operation_preview(store: ReadAgentStore, body: dict[str, Any]) -> dict[str, Any]:
    operation = EditorOperation.model_validate(body["operation"])
    project = store.load_project(body["project_id"])
    semantic_ref = body.get("base_json_version") or _latest_semantic_ref(project, body["floor_id"])
    semantic_json = store.load_output_json_by_ref(semantic_ref)
    stage2_payload = _unwrap(semantic_json)
    object_path, target_object, _collection_key = _find_object(stage2_payload, operation.target.object_id, operation.target.object_type)

    patches: list[dict[str, Any]] = []
    validation = _validate_operation(stage2_payload, operation, target_object)

    # Root path may be /stage2_primary_structure_result or /stage2 depending on semantic JSON.
    if "stage2_primary_structure_result" in semantic_json:
        root_path: list[Any] = ["stage2_primary_structure_result"]
    elif "stage2" in semantic_json:
        root_path = ["stage2"]
        if "stage2_primary_structure_result" in semantic_json["stage2"]:
            root_path.append("stage2_primary_structure_result")
    else:
        root_path = []

    base_path = root_path + object_path
    params = operation.params
    if operation.operation_type in {"update_beam_section", "update_column_section"}:
        patches.append({"op": "replace", "path": _json_pointer(base_path + ["section"]), "value": _parse_section(params.get("section"))})
    if operation.operation_type == "update_beam_label":
        label = str(params.get("label") or "").strip()
        if not label:
            raise HTTPException(status_code=422, detail="label is required")
        patches.append({"op": "replace", "path": _json_pointer(base_path + ["label"]), "value": label})
    if operation.operation_type in {"update_review_status", "accept_object", "reject_object"}:
        status = str(params.get("review_status") or ("rejected" if operation.operation_type == "reject_object" else "accepted"))
        patches.append({"op": "replace", "path": _json_pointer(base_path + ["review_status"]), "value": status})

    if not patches:
        raise HTTPException(status_code=422, detail=f"Unsupported or empty operation: {operation.operation_type}")

    preview_id = make_id("preview")
    return {
        "preview_result_id": preview_id,
        "project_id": body["project_id"],
        "floor_id": body["floor_id"],
        "blueprint_id": body.get("blueprint_id"),
        "base_json_version": semantic_ref,
        "operation": operation.model_dump(mode="json"),
        "json_patch": patches,
        "validation_result": validation,
        "audit_event": {
            "audit_event_id": make_id("audit"),
            "operation_id": operation.operation_id,
            "operation_type": operation.operation_type,
            "actor": operation.actor,
            "target": operation.target.model_dump(mode="json"),
            "base_json_version": semantic_ref,
            "committed": False,
            "ts": _now(),
        },
    }


def _apply_patch(doc: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    result = copy.deepcopy(doc)
    for patch in patches:
        if patch.get("op") != "replace":
            raise HTTPException(status_code=422, detail="Only replace patches are supported by the MVP commit path")
        raw_path = str(patch["path"])
        parts = [p.replace("~1", "/").replace("~0", "~") for p in raw_path.strip("/").split("/") if p != ""]
        typed: list[Any] = [int(p) if p.isdigit() else p for p in parts]
        _set_by_path(result, typed, patch["value"])
    return result


def commit_operation(store: ReadAgentStore, body: dict[str, Any]) -> dict[str, Any]:
    if not body.get("user_confirmation"):
        raise HTTPException(status_code=400, detail="user_confirmation=true is required before committing")
    preview = build_operation_preview(store, body)
    validation = preview["validation_result"]
    if validation["status"] == "failed":
        raise HTTPException(status_code=422, detail={"message": "operation validation failed", "validation_result": validation})

    project = store.load_project(body["project_id"])
    base_ref = preview["base_json_version"]
    old_doc = store.load_output_json_by_ref(base_ref)
    new_doc = _apply_patch(old_doc, preview["json_patch"])
    new_doc.setdefault("edit_history", []).append(
        {
            "operation": preview["operation"],
            "json_patch": preview["json_patch"],
            "validation_result": validation,
            "committed_at": _now(),
        }
    )
    version_id = f"sem_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{make_id('v')}"
    version_ref = store.write_output_json(body["project_id"], body["floor_id"], f"versions/{version_id}.json", new_doc)

    # Update floor current version.
    for building in project.get("buildings", []):
        for floor in building.get("floors", []):
            if floor.get("floor_id") == body["floor_id"]:
                floor["current_semantic_version"] = version_ref
                blueprint_ids = [bp.get("blueprint_id") for bp in floor.get("blueprints", []) if bp.get("blueprint_id")]
                view_model = compile_semantic_view_model(
                    project_id=body["project_id"],
                    floor_id=body["floor_id"],
                    blueprint_ids=blueprint_ids,
                    semantic_json=new_doc,
                    base_json_version=version_ref,
                )
                vm_ref = store.write_output_json(body["project_id"], body["floor_id"], "view_model.json", view_model)
                floor["current_view_model_asset"] = vm_ref
    store.save_project(project)

    audit = preview["audit_event"]
    audit["committed"] = True
    audit["new_json_version"] = version_ref
    audit_ref = store.write_output_json(body["project_id"], body["floor_id"], f"audit/{audit['audit_event_id']}.json", audit)
    return {
        **preview,
        "new_json_version": version_ref,
        "audit_event": audit,
        "audit_ref": audit_ref,
    }
