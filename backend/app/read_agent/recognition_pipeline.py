from __future__ import annotations

import json
import os
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .llm_json import LlmNotConfigured, chat_json, llm_is_configured
from .storage import ReadAgentStore, make_id
from .view_model import compile_semantic_view_model


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _emit(
    store: ReadAgentStore,
    run: dict[str, Any],
    event_type: str,
    title: str,
    *,
    floor_id: str | None = None,
    blueprint_id: str | None = None,
    stage: str | None = None,
    summary: str | None = None,
    payload: dict[str, Any] | None = None,
    artifact_refs: list[str] | None = None,
) -> None:
    store.append_event(
        run["run_id"],
        {
            "run_id": run["run_id"],
            "event_type": event_type,
            "project_id": run["project_id"],
            "floor_id": floor_id,
            "blueprint_id": blueprint_id,
            "stage": stage,
            "title": title,
            "summary": summary,
            "payload": payload or {},
            "artifact_refs": artifact_refs or [],
        },
    )


def _image_size(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None, None


def _make_tiles(
    store: ReadAgentStore,
    project_id: str,
    floor_id: str,
    blueprint_id: str,
    image_path: Path,
) -> list[dict[str, Any]]:
    """Create real high-resolution tiles with overlap.

    This is intentionally generic and does not reproduce PL-S-001. If the user has
    an axis-enhanced tiler, set READ_AGENT_AXIS_TILE_TOOL and replace this function
    with that tool in the pipeline. This generic fallback still produces real
    input crops for LLM/OCR.
    """
    tiles: list[dict[str, Any]] = []
    try:
        from PIL import Image

        with Image.open(image_path) as image:
            width, height = image.size
            if width < 200 or height < 200:
                return []
            overlap_x = int(width * 0.05)
            overlap_y = int(height * 0.05)
            boxes = [
                (0, 0, width // 2 + overlap_x, height // 2 + overlap_y, "tile_top_left"),
                (width // 2 - overlap_x, 0, width, height // 2 + overlap_y, "tile_top_right"),
                (0, height // 2 - overlap_y, width // 2 + overlap_x, height, "tile_bottom_left"),
                (width // 2 - overlap_x, height // 2 - overlap_y, width, height, "tile_bottom_right"),
            ]
            for x0, y0, x1, y1, tile_id in boxes:
                crop = image.crop((x0, y0, x1, y1))
                out = store.outputs_dir(project_id, floor_id) / "crops" / blueprint_id / f"{tile_id}.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                crop.save(out)
                tiles.append(
                    {
                        "tile_id": tile_id,
                        "asset_ref": store.asset_ref(out),
                        "bbox_image_px": [x0, y0, x1, y1],
                        "purpose": "highres_context_crop",
                    }
                )
    except Exception as exc:
        tiles.append({"tile_id": "tile_generation_failed", "error": str(exc), "purpose": "diagnostic"})
    return tiles


def _maybe_ocr(image_path: Path, bbox: list[float] | None = None) -> dict[str, Any] | None:
    if os.environ.get("READ_AGENT_OCR_ENABLED", "1") not in {"1", "true", "TRUE", "yes"}:
        return None
    try:
        from deerflow.tools.paddleocr_client import recognize_sheet_text

        regions = None
        if bbox:
            regions = [{"region_id": "selected_region", "bbox": bbox, "bbox_space": "image_px", "region_type": "manual_ocr_region"}]
        return recognize_sheet_text(str(image_path), regions=regions, endpoint=os.environ.get("PADDLEOCR_ENDPOINT"), include_text_units=True, min_confidence=0.5)
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc), "text_units": []}


def _stage1_prompt() -> tuple[str, str, dict[str, Any]]:
    system = "你是土木结构工程图纸识读 Agent。你必须只输出 JSON，不能编造图纸上没有的信息。"
    user = """
任务：对上传的结构蓝图进行版面分析。
请识别：主结构平面图、详图、表格、说明文字、标题栏、轴网尺寸区域、梁/柱/配筋说明区域。
输出要求：JSON 字段包括 layout_regions、main_plan_candidates、detail_candidates、tables、text_blocks、uncertainties。每个 region 尽量给 bbox_image_px、confidence、evidence_note。
如果图中看不清，请把字段放入 uncertainties，不要猜。
""".strip()
    schema = {"layout_regions": [], "main_plan_candidates": [], "detail_candidates": [], "tables": [], "text_blocks": [], "uncertainties": []}
    return system, user, schema


def _stage2_prompt(stage1: dict[str, Any], ocr: dict[str, Any] | None) -> tuple[str, str, dict[str, Any]]:
    system = "你是结构平面图识读 Agent。输出必须是结构化 JSON。不要使用示例数据，不要补造缺失截面。"
    user = f"""
任务：针对主结构平面图识别轴网、柱网、主梁，并输出可编辑语义 JSON。
识图规则：
- 轴网通常为点划线，轴号在边缘圆圈中，轴距为尺寸标注。
- 柱通常为实心或空心正方形/矩形，主轴交点处柱要绑定 grid_node。
- 主梁通常为双实线或双虚线，起止在柱上；多跨主梁需要合并输出，同时保留 spans/edges。
- 梁标签如 KL5(6) 600x1200，截面需拆成 width_mm / height_mm。
- 看不清的字段必须写入 uncertainties，不允许猜测。

Stage1 摘要：{json.dumps(stage1, ensure_ascii=False)[:8000]}
OCR 摘要：{json.dumps(ocr or {}, ensure_ascii=False)[:8000]}

输出字段建议：
recognition_status, grid, columns, main_beams, graph, evidence, uncertainties, quality。
""".strip()
    schema = {
        "recognition_status": "recognized|review_required|insufficient_evidence",
        "grid": {"x_labels": [], "x_spacings_mm": [], "y_labels": [], "y_spacings_mm": []},
        "columns": [],
        "main_beams": [],
        "graph": {"nodes": [], "edges": []},
        "evidence": [],
        "uncertainties": [],
        "quality": {},
    }
    return system, user, schema


def _stage3_prompt(stage1: dict[str, Any], stage2: dict[str, Any], ocr: dict[str, Any] | None) -> tuple[str, str, dict[str, Any]]:
    system = "你是结构详图和次要结构候选识别 Agent。输出 JSON，候选对象不要直接升级为正式主模型。"
    user = f"""
任务：识别次梁、洞口、楼梯/井道、平台标注、详图索引、表格候选。
这些对象默认是 candidates，必须带证据、置信度和 review_status。
Stage1：{json.dumps(stage1, ensure_ascii=False)[:6000]}
Stage2：{json.dumps(stage2, ensure_ascii=False)[:6000]}
OCR：{json.dumps(ocr or {}, ensure_ascii=False)[:6000]}
""".strip()
    schema = {"secondary_beam_candidates": [], "opening_candidates": [], "detail_callouts": [], "text_annotation_candidates": [], "uncertainties": []}
    return system, user, schema


def _call_llm_or_blocker(stage: str, system_prompt: str, user_prompt: str, schema: dict[str, Any], images: list[Path]) -> dict[str, Any]:
    if not llm_is_configured():
        return {
            "recognition_status": "blocked_waiting_for_model",
            "stage": stage,
            "message": "No READ_AGENT_LLM_API_KEY/OPENAI_API_KEY configured. Runtime did not fabricate results.",
            "expected_output_schema": schema,
            "uncertainties": [{"code": "llm_not_configured", "message": "Configure a vision LLM to run recognition."}],
        }
    try:
        return chat_json(system_prompt=system_prompt, user_prompt=user_prompt, image_paths=images, response_schema_hint=schema)
    except LlmNotConfigured:
        raise
    except Exception as exc:
        return {
            "recognition_status": "failed",
            "stage": stage,
            "error": str(exc),
            "expected_output_schema": schema,
            "uncertainties": [{"code": "llm_call_failed", "message": str(exc)}],
        }


def _selected_blueprints(project: dict[str, Any], run: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    selected = set(run.get("blueprint_ids") or [])
    floor_ids = set(run.get("floor_ids") or [])
    result: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for building in project.get("buildings", []):
        for floor in building.get("floors", []):
            for blueprint in floor.get("blueprints", []):
                if selected and blueprint.get("blueprint_id") not in selected:
                    continue
                if floor_ids and floor.get("floor_id") not in floor_ids:
                    continue
                result.append((building, floor, blueprint))
    return result


def run_read_agent_pipeline(data_root: str, run_id: str) -> None:
    store = ReadAgentStore(data_root)
    run = store.load_run(run_id)
    project = store.load_project(run["project_id"])
    store.update_run_status(run_id, "running")
    _emit(store, run, "run.started", "读图任务启动", summary="开始处理项目蓝图，后续事件均来自真实上传文件和运行时工具。")

    artifact_refs: dict[str, Any] = {"stage1": [], "stage2": [], "stage3": [], "view_models": []}
    try:
        selected = _selected_blueprints(project, run)
        if not selected:
            raise RuntimeError("No blueprints selected for recognition")

        floor_stage2_docs: dict[str, list[dict[str, Any]]] = {}
        floor_blueprints: dict[str, list[str]] = {}

        for _building, floor, blueprint in selected:
            floor_id = floor["floor_id"]
            blueprint_id = blueprint["blueprint_id"]
            floor_blueprints.setdefault(floor_id, []).append(blueprint_id)
            image_path = store.resolve_asset(blueprint["asset_ref"])
            _emit(store, run, "blueprint.started", "开始处理蓝图", floor_id=floor_id, blueprint_id=blueprint_id, stage="blueprint", payload={"asset_ref": blueprint["asset_ref"]})
            stage2: dict[str, Any] = {}

            width, height = _image_size(image_path)
            tiles = _make_tiles(store, run["project_id"], floor_id, blueprint_id, image_path) if image_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else []
            tile_refs = [tile["asset_ref"] for tile in tiles if tile.get("asset_ref")]
            stage1_base = {
                "schema_version": "cv-notfunning/stage1-layout/v1.0",
                "project_id": run["project_id"],
                "floor_id": floor_id,
                "blueprint_id": blueprint_id,
                "source_asset_ref": blueprint["asset_ref"],
                "image_size_px": [width, height],
                "generated_tiles": tiles,
                "created_at": _now(),
            }
            _emit(store, run, "tool.completed", "切片完成", floor_id=floor_id, blueprint_id=blueprint_id, stage="stage1", summary=f"生成 {len(tile_refs)} 个高清上下文切片。", artifact_refs=tile_refs)

            ocr = _maybe_ocr(image_path)
            ocr_ref = store.write_output_json(run["project_id"], floor_id, f"stage1/{blueprint_id}_ocr.json", ocr or {"status": "disabled"})
            _emit(store, run, "tool.completed", "OCR 完成", floor_id=floor_id, blueprint_id=blueprint_id, stage="stage1", payload={"ocr_status": (ocr or {}).get("status", "disabled")}, artifact_refs=[ocr_ref])

            images_for_stage1 = [image_path]
            system, user, schema = _stage1_prompt()
            stage1_llm = _call_llm_or_blocker("stage1", system, user, schema, images_for_stage1)
            stage1 = {**stage1_base, **stage1_llm}
            stage1_ref = store.write_output_json(run["project_id"], floor_id, f"stage1/{blueprint_id}_layout.json", stage1)
            artifact_refs["stage1"].append(stage1_ref)
            _emit(store, run, "stage.completed", "Stage1 版面分析完成", floor_id=floor_id, blueprint_id=blueprint_id, stage="stage1", artifact_refs=[stage1_ref])

            if "stage2" in run.get("target_stages", []):
                stage2_images = [image_path]
                for ref in tile_refs[:4]:
                    try:
                        stage2_images.append(store.resolve_asset(ref))
                    except Exception:
                        pass
                system, user, schema = _stage2_prompt(stage1, ocr)
                stage2 = _call_llm_or_blocker("stage2", system, user, schema, stage2_images)
                stage2 = {
                    "schema_version": "cv-notfunning/stage2-primary-structure/v1.0",
                    "project_id": run["project_id"],
                    "floor_id": floor_id,
                    "blueprint_id": blueprint_id,
                    "source_asset_ref": blueprint["asset_ref"],
                    "created_at": _now(),
                    "stage2_primary_structure_result": stage2,
                }
                stage2_ref = store.write_output_json(run["project_id"], floor_id, f"stage2/{blueprint_id}_primary_structure.json", stage2)
                artifact_refs["stage2"].append(stage2_ref)
                floor_stage2_docs.setdefault(floor_id, []).append(stage2)
                _emit(store, run, "stage.completed", "Stage2 轴网柱网主梁识别完成", floor_id=floor_id, blueprint_id=blueprint_id, stage="stage2", artifact_refs=[stage2_ref])

            if "stage3" in run.get("target_stages", []):
                system, user, schema = _stage3_prompt(stage1, stage2 if "stage2" in locals() else {}, ocr)
                stage3 = _call_llm_or_blocker("stage3", system, user, schema, [image_path])
                stage3_doc = {
                    "schema_version": "cv-notfunning/stage3-candidates/v1.0",
                    "project_id": run["project_id"],
                    "floor_id": floor_id,
                    "blueprint_id": blueprint_id,
                    "source_asset_ref": blueprint["asset_ref"],
                    "created_at": _now(),
                    "stage3_candidates_result": stage3,
                }
                stage3_ref = store.write_output_json(run["project_id"], floor_id, f"stage3/{blueprint_id}_candidates.json", stage3_doc)
                artifact_refs["stage3"].append(stage3_ref)
                _emit(store, run, "stage.completed", "Stage3 候选对象识别完成", floor_id=floor_id, blueprint_id=blueprint_id, stage="stage3", artifact_refs=[stage3_ref])

        # Compile one semantic version per floor, combining all selected blueprints.
        project = store.load_project(run["project_id"])
        for floor_id, docs in floor_stage2_docs.items():
            combined = _combine_floor_stage2_docs(run["project_id"], floor_id, docs)
            version_id = f"sem_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{make_id('v')}"
            version_ref = store.write_output_json(run["project_id"], floor_id, f"versions/{version_id}.json", combined)
            view_model = compile_semantic_view_model(
                project_id=run["project_id"],
                floor_id=floor_id,
                blueprint_ids=floor_blueprints.get(floor_id, []),
                semantic_json=combined,
                base_json_version=version_ref,
            )
            vm_ref = store.write_output_json(run["project_id"], floor_id, "view_model.json", view_model)
            artifact_refs["view_models"].append(vm_ref)
            for building in project.get("buildings", []):
                for floor in building.get("floors", []):
                    if floor.get("floor_id") == floor_id:
                        floor["current_semantic_version"] = version_ref
                        floor["current_view_model_asset"] = vm_ref
                        for bp in floor.get("blueprints", []):
                            if bp.get("blueprint_id") in floor_blueprints.get(floor_id, []):
                                bp["status"] = "ready_for_edit"
                                bp["updated_at"] = _now()
            _emit(store, run, "view_model.updated", "语义 ViewModel 已生成", floor_id=floor_id, stage="view_model", artifact_refs=[vm_ref], payload={"object_count": view_model.get("quality", {}).get("object_count")})
        store.save_project(project)
        store.update_run_status(run_id, "ready_for_edit", edit_base_version=artifact_refs["view_models"][0] if artifact_refs["view_models"] else None, artifact_refs=artifact_refs)
        _emit(store, run, "ready_for_edit", "读图完成，可进入编辑模式", stage="ready", summary="已生成 floor-level semantic JSON 和 ViewModel。", artifact_refs=artifact_refs.get("view_models", []), payload={"artifact_refs": artifact_refs})
    except Exception as exc:
        trace = traceback.format_exc()
        store.update_run_status(run_id, "failed", error=str(exc), artifact_refs=artifact_refs)
        _emit(store, run, "run.failed", "读图任务失败", stage="failed", summary=str(exc), payload={"traceback": trace[-4000:]})


def _combine_floor_stage2_docs(project_id: str, floor_id: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine multiple blueprint Stage2 outputs for the same floor.

    The first recognized grid is used as the floor grid. Objects from all blueprints
    are namespaced if object IDs collide. This is deliberately conservative and
    records conflicts instead of silently merging incompatible grids.
    """
    combined_payload: dict[str, Any] = {
        "recognition_status": "combined",
        "grid": {},
        "columns": [],
        "main_beams": [],
        "graph": {"nodes": [], "edges": []},
        "evidence": [],
        "uncertainties": [],
        "quality": {"source_blueprint_count": len(docs)},
    }
    seen_ids: set[str] = set()
    for doc in docs:
        bp = doc.get("blueprint_id")
        payload = doc.get("stage2_primary_structure_result") or {}
        if not combined_payload["grid"] and payload.get("grid"):
            combined_payload["grid"] = payload["grid"]
        elif payload.get("grid") and payload.get("grid") != combined_payload.get("grid"):
            combined_payload["uncertainties"].append({"code": "grid_conflict", "blueprint_id": bp, "message": "Stage2 grids differ; manual review required."})
        for key in ["columns", "main_beams"]:
            for item in payload.get(key, []) if isinstance(payload.get(key), list) else []:
                item = dict(item)
                item.setdefault("source_blueprint_id", bp)
                oid = str(item.get("object_id") or item.get("id") or item.get("beam_id") or item.get("column_id") or f"{key}-{len(seen_ids)}")
                if oid in seen_ids:
                    oid = f"{bp}-{oid}"
                item["object_id"] = oid
                seen_ids.add(oid)
                combined_payload[key].append(item)
        if isinstance(payload.get("graph"), dict):
            combined_payload["graph"].setdefault("nodes", []).extend(payload["graph"].get("nodes", []))
            combined_payload["graph"].setdefault("edges", []).extend(payload["graph"].get("edges", []))
        combined_payload["evidence"].extend(payload.get("evidence", []) if isinstance(payload.get("evidence"), list) else [])
        combined_payload["uncertainties"].extend(payload.get("uncertainties", []) if isinstance(payload.get("uncertainties"), list) else [])
    return {
        "schema_version": "cv-notfunning/floor-semantic-json/v1.0",
        "project_id": project_id,
        "floor_id": floor_id,
        "created_at": _now(),
        "stage2_primary_structure_result": combined_payload,
    }
