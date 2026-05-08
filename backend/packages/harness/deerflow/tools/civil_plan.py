from __future__ import annotations

import json
import math
import posixpath
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


_HARNESS_CONTAINER_PATH = "/mnt/harness-workbench"
_PROMPT_CONTAINER_PATH = "/mnt/prompt-workbench"


def _lab_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _configured_mounts() -> list[tuple[str, Path]]:
    mounts: list[tuple[str, Path]] = []
    try:
        from deerflow.config import get_app_config

        for mount in get_app_config().sandbox.mounts:
            host_path = Path(mount.host_path)
            if host_path.exists():
                mounts.append((mount.container_path.rstrip("/"), host_path))
    except Exception:
        pass

    root = _lab_root()
    fallbacks = [
        (_HARNESS_CONTAINER_PATH, root / "harness-workbench"),
        (_PROMPT_CONTAINER_PATH, root / "prompt-workbench"),
    ]
    for container_path, host_path in fallbacks:
        if host_path.exists() and all(container_path != existing for existing, _ in mounts):
            mounts.append((container_path, host_path))
    return mounts


def _resolve_drawing_path(drawing_path: str) -> Path:
    path = Path(drawing_path)
    if path.exists():
        return path

    normalized = posixpath.normpath(drawing_path)
    for container_path, host_path in _configured_mounts():
        if normalized == container_path or normalized.startswith(f"{container_path}/"):
            relative = normalized[len(container_path) :].lstrip("/")
            candidate = (host_path / relative).resolve()
            candidate.relative_to(host_path.resolve())
            if candidate.exists():
                return candidate

    raise FileNotFoundError(f"Civil plan drawing not found: {drawing_path}")


def _float_attr(element: ET.Element, name: str, default: float = 0.0) -> float:
    raw = element.attrib.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _round(value: float) -> float:
    if math.isclose(value, round(value), abs_tol=1e-9):
        return float(round(value))
    return round(value, 3)


def _elements_by_role(root: ET.Element, role: str) -> list[ET.Element]:
    return [element for element in root.iter() if element.attrib.get("data-role") == role]


def _plan_metadata(root: ET.Element) -> ET.Element | None:
    for element in root.iter():
        if element.attrib.get("data-role") == "plan":
            return element
    return None


def analyze_civil_plan_file(drawing_path: str) -> dict[str, Any]:
    """Analyze a civil structural floor plan SVG and return computed quantities."""
    resolved_path = _resolve_drawing_path(drawing_path)
    tree = ET.parse(resolved_path)
    root = tree.getroot()
    metadata = _plan_metadata(root)

    columns = _elements_by_role(root, "column")
    beams = _elements_by_role(root, "beam")
    slabs = _elements_by_role(root, "slab")

    beam_spans = [_float_attr(beam, "data-span-m") for beam in beams]
    floor_area = sum(_float_attr(slab, "data-area-m2") for slab in slabs)
    total_load_kpa = _float_attr(metadata, "data-total-load-kpa") if metadata is not None else 0.0
    total_vertical_load = floor_area * total_load_kpa

    result = {
        "drawing_id": root.attrib.get("data-drawing-id", resolved_path.stem),
        "source_path": drawing_path,
        "resolved_path": str(resolved_path),
        "units": root.attrib.get("data-units", "m"),
        "grid_x_axes": metadata.attrib.get("data-x-axes", "") if metadata is not None else "",
        "grid_y_axes": metadata.attrib.get("data-y-axes", "") if metadata is not None else "",
        "column_count": len(columns),
        "column_grids": [column.attrib.get("data-grid", "") for column in columns],
        "beam_count": len(beams),
        "beam_ids": [beam.attrib.get("data-id", "") for beam in beams],
        "max_beam_span_m": _round(max(beam_spans) if beam_spans else 0.0),
        "floor_area_m2": _round(floor_area),
        "total_load_kpa": _round(total_load_kpa),
        "total_vertical_load_kN": _round(total_vertical_load),
    }
    result["answer"] = (
        f"柱数量{result['column_count']}根；"
        f"梁数量{result['beam_count']}根；"
        f"最大梁跨度{result['max_beam_span_m']:.1f} m；"
        f"楼板面积{result['floor_area_m2']:.1f} m2；"
        f"总竖向荷载{result['total_vertical_load_kN']:.1f} kN。"
    )
    return result


def _analyze_civil_plan_tool(drawing_path: str, question: str = "") -> str:
    """Analyze a civil structural floor plan drawing.

    Args:
        drawing_path: Path to an SVG civil structural plan, usually under /mnt/harness-workbench.
        question: The recognition question to answer from the drawing.
    """
    result = analyze_civil_plan_file(drawing_path)
    if question:
        result["question"] = question
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


try:
    from langchain.tools import tool

    analyze_civil_plan_tool = tool("analyze_civil_plan", parse_docstring=True)(_analyze_civil_plan_tool)
except Exception:

    class _FallbackCivilPlanTool:
        name = "analyze_civil_plan"
        description = "Analyze a civil structural floor plan drawing."

        def invoke(self, args: dict[str, Any]) -> str:
            return _analyze_civil_plan_tool(**args)

    analyze_civil_plan_tool = _FallbackCivilPlanTool()
