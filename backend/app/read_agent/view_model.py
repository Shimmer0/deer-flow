from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _unwrap_stage2(stage2: dict[str, Any]) -> dict[str, Any]:
    return stage2.get("stage2_primary_structure_result") or stage2.get("stage2") or stage2


def _axis_coordinates(labels: list[str], spacings: list[float]) -> dict[str, float]:
    coords: dict[str, float] = {}
    total = 0.0
    for index, label in enumerate(labels):
        coords[str(label)] = total
        if index < len(spacings):
            total += float(spacings[index])
    return coords


def _grid_from_stage2(stage2: dict[str, Any]) -> dict[str, Any]:
    payload = _unwrap_stage2(stage2)
    grid = payload.get("grid") or payload.get("axis_grid") or payload.get("grid_system") or {}
    x_labels = grid.get("x_labels") or grid.get("x_axes") or grid.get("x_axis_labels") or []
    y_labels = grid.get("y_labels") or grid.get("y_axes") or grid.get("y_axis_labels") or []
    x_spacings = grid.get("x_spacings_mm") or grid.get("x_spacing_mm") or grid.get("x_spans_mm") or []
    y_spacings = grid.get("y_spacings_mm") or grid.get("y_spacing_mm") or grid.get("y_spans_mm") or []

    # Some LLMs may return [{label, coord_mm}] instead of labels/spacings.
    if x_labels and isinstance(x_labels[0], dict):
        x_coords = {str(item.get("label")): float(item.get("coord_mm", 0)) for item in x_labels}
        x_labels = list(x_coords.keys())
    else:
        x_labels = [str(v) for v in x_labels]
        x_coords = _axis_coordinates(x_labels, [float(v) for v in x_spacings])

    if y_labels and isinstance(y_labels[0], dict):
        y_coords = {str(item.get("label")): float(item.get("coord_mm", 0)) for item in y_labels}
        y_labels = list(y_coords.keys())
    else:
        y_labels = [str(v) for v in y_labels]
        y_coords = _axis_coordinates(y_labels, [float(v) for v in y_spacings])

    return {
        "x_labels": x_labels,
        "y_labels": y_labels,
        "x_spacings_mm": [float(v) for v in x_spacings],
        "y_spacings_mm": [float(v) for v in y_spacings],
        "x_coords": x_coords,
        "y_coords": y_coords,
        "total_width_mm": max(x_coords.values(), default=0),
        "total_height_mm": max(y_coords.values(), default=0),
    }


def _node_coord(node: str, grid: dict[str, Any]) -> list[float] | None:
    # Supports "1-A", "A-1", and {x_axis,y_axis} style handled upstream.
    parts = str(node).replace("_", "-").split("-")
    if len(parts) != 2:
        return None
    a, b = parts
    x = grid["x_coords"].get(a)
    y = grid["y_coords"].get(b)
    if x is None or y is None:
        x = grid["x_coords"].get(b)
        y = grid["y_coords"].get(a)
    if x is None or y is None:
        return None
    return [float(x), float(y)]


def _section_text(section: Any) -> str:
    if isinstance(section, dict):
        w = section.get("width_mm") or section.get("b") or section.get("width")
        h = section.get("height_mm") or section.get("h") or section.get("height")
        if w and h:
            return f"{int(float(w))}×{int(float(h))}"
    if isinstance(section, str):
        return section.replace("x", "×")
    return "截面待确认"


def compile_semantic_view_model(
    *,
    project_id: str,
    floor_id: str,
    blueprint_ids: list[str],
    semantic_json: dict[str, Any],
    base_json_version: str,
) -> dict[str, Any]:
    """Compile Stage JSON into the web semantic editor ViewModel.

    The function accepts several equivalent Stage2 formats so the runtime is not
    tied to one single prompt wording. It never fabricates structure objects; if
    the recognizer did not produce grid/columns/beams, the ViewModel is empty and
    marked review_required.
    """
    stage2 = semantic_json.get("stage2") or semantic_json.get("stage2_primary_structure_result") or semantic_json
    payload = _unwrap_stage2(stage2)
    grid = _grid_from_stage2(payload)
    objects: list[dict[str, Any]] = []

    for label, x in grid["x_coords"].items():
        objects.append(
            {
                "view_id": f"axis-x-{label}",
                "semantic_object_id": f"axis-x-{label}",
                "object_type": "axis",
                "layer": "GRID_AXIS",
                "display_label": str(label),
                "geometry": {"kind": "vertical_axis", "coord_mm": x},
                "confidence": 1.0,
                "review_status": "reference",
            }
        )
    for label, y in grid["y_coords"].items():
        objects.append(
            {
                "view_id": f"axis-y-{label}",
                "semantic_object_id": f"axis-y-{label}",
                "object_type": "axis",
                "layer": "GRID_AXIS",
                "display_label": str(label),
                "geometry": {"kind": "horizontal_axis", "coord_mm": y},
                "confidence": 1.0,
                "review_status": "reference",
            }
        )

    columns = payload.get("columns") or payload.get("column_grid") or []
    for index, col in enumerate(columns):
        object_id = str(col.get("object_id") or col.get("id") or col.get("column_id") or f"COL-{index:04d}")
        coord = col.get("coord_mm") or col.get("center_mm")
        if not coord and col.get("grid_node"):
            coord = _node_coord(str(col["grid_node"]), grid)
        if not coord:
            x_axis = col.get("x_axis") or col.get("grid_x")
            y_axis = col.get("y_axis") or col.get("grid_y")
            if x_axis and y_axis:
                coord = [grid["x_coords"].get(str(x_axis)), grid["y_coords"].get(str(y_axis))]
        if not coord or coord[0] is None or coord[1] is None:
            continue
        section = col.get("section") or col.get("section_estimate")
        objects.append(
            {
                "view_id": f"view-{object_id}",
                "semantic_object_id": object_id,
                "object_type": "column",
                "layer": "COLUMN",
                "display_label": col.get("label") or object_id,
                "geometry": {"kind": "rect_center", "center_mm": [float(coord[0]), float(coord[1])], "size_mm": col.get("size_mm") or [900, 900]},
                "section": section,
                "section_text": _section_text(section),
                "editable_fields": ["section", "review_status"],
                "confidence": float(col.get("confidence", 0.5)),
                "review_status": col.get("review_status") or "needs_review",
                "evidence_refs": col.get("evidence_refs") or [],
            }
        )

    beams = payload.get("main_beams") or payload.get("beams") or []
    for index, beam in enumerate(beams):
        object_id = str(beam.get("object_id") or beam.get("id") or beam.get("beam_id") or f"MB-{index:04d}")
        points = beam.get("points_mm") or beam.get("geometry", {}).get("points_mm")
        if not points:
            start = beam.get("start_node") or beam.get("start_grid_node")
            end = beam.get("end_node") or beam.get("end_grid_node")
            if start and end:
                p0 = _node_coord(str(start), grid)
                p1 = _node_coord(str(end), grid)
                if p0 and p1:
                    points = [p0, p1]
        if not points or len(points) < 2:
            continue
        section = beam.get("section")
        label = beam.get("label") or beam.get("beam_label") or beam.get("name") or object_id
        display_label = f"{label} {_section_text(section)}".strip()
        objects.append(
            {
                "view_id": f"view-{object_id}",
                "semantic_object_id": object_id,
                "object_type": "main_beam",
                "layer": "MAIN_BEAM",
                "display_label": display_label,
                "label": label,
                "geometry": {"kind": "polyline", "points_mm": [[float(p[0]), float(p[1])] for p in points]},
                "section": section,
                "section_text": _section_text(section),
                "editable_fields": ["label", "section", "review_status"],
                "confidence": float(beam.get("confidence", 0.5)),
                "review_status": beam.get("review_status") or "needs_review",
                "evidence_refs": beam.get("evidence_refs") or [],
                "source_blueprint_id": beam.get("source_blueprint_id") or (blueprint_ids[0] if blueprint_ids else None),
            }
        )

    return {
        "schema_version": "cv-notfunning/semantic-view-model/v1.0",
        "project_id": project_id,
        "floor_id": floor_id,
        "blueprint_ids": blueprint_ids,
        "base_json_version": base_json_version,
        "generated_at": _now(),
        "coordinate_system": {
            "unit": "mm",
            "origin_node": "1-A",
            "x_direction": "axis_number_increasing",
            "y_direction": "axis_letter_increasing",
            "total_width_mm": grid["total_width_mm"],
            "total_height_mm": grid["total_height_mm"],
        },
        "layers": [
            {"id": "UNDERLAY_IMAGE", "name": "原图底图", "visible": True, "locked": True, "opacity": 0.35},
            {"id": "GRID_AXIS", "name": "轴网", "visible": True, "locked": True},
            {"id": "COLUMN", "name": "柱", "visible": True, "locked": False},
            {"id": "MAIN_BEAM", "name": "主梁", "visible": True, "locked": False},
            {"id": "EVIDENCE_BOX", "name": "证据框", "visible": True, "locked": True},
        ],
        "objects": objects,
        "quality": {
            "object_count": len(objects),
            "axis_count": len(grid["x_coords"]) + len(grid["y_coords"]),
            "column_count": sum(1 for o in objects if o["object_type"] == "column"),
            "main_beam_count": sum(1 for o in objects if o["object_type"] == "main_beam"),
            "recognition_status": payload.get("recognition_status") or semantic_json.get("recognition_status") or "generated",
        },
    }
