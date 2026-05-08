from __future__ import annotations

import json
import posixpath
from pathlib import Path
from typing import Any

from PIL import Image


_HARNESS_CONTAINER_PATH = "/mnt/harness-workbench"
_GPT_PRO_CONTAINER_PATH = "/mnt/gpt-pro"


def _lab_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _allowed_input_mounts() -> list[tuple[str, Path]]:
    root = _lab_root()
    return [
        (_HARNESS_CONTAINER_PATH, root / "harness-workbench"),
        (_GPT_PRO_CONTAINER_PATH, root / "docs" / "GPT_PRO"),
    ]


def _resolve_input_path(image_path: str) -> Path:
    normalized = posixpath.normpath(image_path)
    for container_path, host_path in _allowed_input_mounts():
        if normalized == container_path or normalized.startswith(f"{container_path}/"):
            relative = normalized[len(container_path) :].lstrip("/")
            candidate = (host_path / relative).resolve()
            candidate.relative_to(host_path.resolve())
            if not candidate.is_file():
                raise FileNotFoundError(f"Image not found: {image_path}")
            return candidate

    candidate = Path(image_path).expanduser().resolve()
    allowed_roots = [
        (_lab_root() / "harness-workbench").resolve(),
        (_lab_root() / "docs" / "GPT_PRO").resolve(),
        Path("/tmp").resolve(),
    ]
    for allowed_root in allowed_roots:
        try:
            candidate.relative_to(allowed_root)
            if not candidate.is_file():
                raise FileNotFoundError(f"Image not found: {image_path}")
            return candidate
        except ValueError:
            continue
    raise PermissionError("Image path must be under /mnt/harness-workbench, /mnt/gpt-pro, or /tmp")


def _resolve_output_dir(output_dir: str) -> Path:
    normalized = posixpath.normpath(output_dir)
    if normalized == _HARNESS_CONTAINER_PATH or normalized.startswith(f"{_HARNESS_CONTAINER_PATH}/"):
        relative = normalized[len(_HARNESS_CONTAINER_PATH) :].lstrip("/")
        candidate = _lab_root() / "harness-workbench" / relative
    else:
        candidate = Path(output_dir)
    resolved = candidate.expanduser().resolve()
    for allowed_root in [(_lab_root() / "harness-workbench").resolve(), Path("/tmp").resolve()]:
        try:
            resolved.relative_to(allowed_root)
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved
        except ValueError:
            continue
    raise PermissionError("Output directory must be under /mnt/harness-workbench or /tmp")


def _bbox(value: list[int] | tuple[int, int, int, int], name: str) -> tuple[int, int, int, int]:
    if len(value) != 4:
        raise ValueError(f"{name} must contain four integers")
    x0, y0, x1, y1 = [int(v) for v in value]
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{name} must be [x0, y0, x1, y1] with positive width and height")
    return x0, y0, x1, y1


def _clip(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = box
    clipped = (max(0, x0), max(0, y0), min(width, x1), min(height, y1))
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return None
    return clipped


def _ensure_min_strip(
    box: tuple[int, int, int, int] | None,
    side: str,
    crop_box: tuple[int, int, int, int],
    min_strip_px: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    if box is None:
        return None
    x0, y0, x1, y1 = box
    crop_x0, crop_y0, crop_x1, crop_y1 = crop_box
    if side == "left_strip" and x1 - x0 < min_strip_px:
        x0 = max(0, crop_x0 - min_strip_px)
        x1 = crop_x0
    elif side == "right_strip" and x1 - x0 < min_strip_px:
        x0 = crop_x1
        x1 = min(width, crop_x1 + min_strip_px)
    elif side == "top_strip" and y1 - y0 < min_strip_px:
        y0 = max(0, crop_y0 - min_strip_px)
        y1 = crop_y0
    elif side == "bottom_strip" and y1 - y0 < min_strip_px:
        y0 = crop_y1
        y1 = min(height, crop_y1 + min_strip_px)
    return _clip((x0, y0, x1, y1), width, height)


def _component(
    source: Image.Image,
    page_bbox: tuple[int, int, int, int],
    canvas_xy: tuple[int, int],
    kind: str,
    axis_label_backfill: bool,
) -> tuple[Image.Image, dict[str, Any]]:
    crop = source.crop(page_bbox)
    x, y = canvas_xy
    w, h = crop.size
    return crop, {
        "kind": kind,
        "page_bbox_px": list(page_bbox),
        "canvas_bbox_px": [x, y, x + w, y + h],
        "axis_label_backfill": axis_label_backfill,
        "participates_in_merge": True,
    }


def create_axis_context_crop(
    image_path: str,
    crop_bbox_px: list[int],
    axis_frame_bbox_px: list[int],
    output_dir: str,
    crop_id: str = "axis_context_crop",
    min_strip_px: int = 96,
) -> dict[str, Any]:
    """Create a grid crop with surrounding axis-label context strips."""
    resolved_image = _resolve_input_path(image_path)
    resolved_output = _resolve_output_dir(output_dir)
    crop_box = _bbox(crop_bbox_px, "crop_bbox_px")
    frame_box = _bbox(axis_frame_bbox_px, "axis_frame_bbox_px")
    min_strip = max(1, int(min_strip_px))

    with Image.open(resolved_image) as opened:
        source = opened.convert("RGB")
    width, height = source.size
    crop_box = _clip(crop_box, width, height)
    frame_box = _clip(frame_box, width, height)
    if crop_box is None or frame_box is None:
        raise ValueError("crop_bbox_px and axis_frame_bbox_px must intersect the source image")

    crop_x0, crop_y0, crop_x1, crop_y1 = crop_box
    frame_x0, frame_y0, frame_x1, frame_y1 = frame_box
    main = source.crop(crop_box)
    main_w, main_h = main.size
    strips = {
        "top_strip": _ensure_min_strip(_clip((crop_x0, frame_y0, crop_x1, crop_y0), width, height), "top_strip", crop_box, min_strip, width, height),
        "bottom_strip": _ensure_min_strip(_clip((crop_x0, crop_y1, crop_x1, frame_y1), width, height), "bottom_strip", crop_box, min_strip, width, height),
        "left_strip": _ensure_min_strip(_clip((frame_x0, crop_y0, crop_x0, crop_y1), width, height), "left_strip", crop_box, min_strip, width, height),
        "right_strip": _ensure_min_strip(_clip((crop_x1, crop_y0, frame_x1, crop_y1), width, height), "right_strip", crop_box, min_strip, width, height),
    }
    left_w = strips["left_strip"][2] - strips["left_strip"][0] if strips["left_strip"] else 0
    right_w = strips["right_strip"][2] - strips["right_strip"][0] if strips["right_strip"] else 0
    top_h = strips["top_strip"][3] - strips["top_strip"][1] if strips["top_strip"] else 0
    bottom_h = strips["bottom_strip"][3] - strips["bottom_strip"][1] if strips["bottom_strip"] else 0
    canvas = Image.new("RGB", (left_w + main_w + right_w, top_h + main_h + bottom_h), "white")

    components: dict[str, Any] = {}
    if strips["top_strip"]:
        image, meta = _component(source, strips["top_strip"], (left_w, 0), "top_strip", True)
        canvas.paste(image, (left_w, 0))
        components["top_strip"] = meta
    if strips["left_strip"]:
        image, meta = _component(source, strips["left_strip"], (0, top_h), "left_strip", True)
        canvas.paste(image, (0, top_h))
        components["left_strip"] = meta
    canvas.paste(main, (left_w, top_h))
    components["main"] = {
        "kind": "main",
        "page_bbox_px": list(crop_box),
        "canvas_bbox_px": [left_w, top_h, left_w + main_w, top_h + main_h],
        "axis_label_backfill": False,
        "participates_in_merge": True,
    }
    if strips["right_strip"]:
        image, meta = _component(source, strips["right_strip"], (left_w + main_w, top_h), "right_strip", True)
        canvas.paste(image, (left_w + main_w, top_h))
        components["right_strip"] = meta
    if strips["bottom_strip"]:
        image, meta = _component(source, strips["bottom_strip"], (left_w, top_h + main_h), "bottom_strip", True)
        canvas.paste(image, (left_w, top_h + main_h))
        components["bottom_strip"] = meta

    image_out = resolved_output / f"{crop_id}.png"
    meta_out = resolved_output / f"{crop_id}.meta.json"
    result = {
        "status": "pass",
        "crop_id": crop_id,
        "source_image_path": str(resolved_image),
        "image_path": str(image_out),
        "meta_path": str(meta_out),
        "composed_size_px": {"width": canvas.size[0], "height": canvas.size[1]},
        "axis_label_backfill": {
            "strategy": "side_strip_context",
            "source": "PaddleOCR-inspired axis-frame side strip projection",
            "min_strip_px": min_strip,
        },
        "components": components,
    }
    canvas.save(image_out)
    meta_out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _create_axis_context_crop_tool(
    image_path: str,
    crop_bbox_px: list[int],
    axis_frame_bbox_px: list[int],
    output_dir: str,
    crop_id: str = "axis_context_crop",
    min_strip_px: int = 96,
) -> str:
    """Create a crop plus axis-label side strips.

    Args:
        image_path: Source image path under /mnt/harness-workbench or /mnt/gpt-pro.
        crop_bbox_px: Main crop [x0, y0, x1, y1] in source pixels.
        axis_frame_bbox_px: Outer axis-label frame [x0, y0, x1, y1] in source pixels.
        output_dir: Output directory under /mnt/harness-workbench.
        crop_id: Stable crop id used for output filenames.
        min_strip_px: Minimum side strip thickness in pixels.
    """
    result = create_axis_context_crop(
        image_path=image_path,
        crop_bbox_px=crop_bbox_px,
        axis_frame_bbox_px=axis_frame_bbox_px,
        output_dir=output_dir,
        crop_id=crop_id,
        min_strip_px=min_strip_px,
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


try:
    from langchain.tools import tool

    create_axis_context_crop_tool = tool("create_axis_context_crop", parse_docstring=True)(_create_axis_context_crop_tool)
except Exception:

    class _FallbackAxisContextCropTool:
        name = "create_axis_context_crop"
        description = "Create a crop plus axis-label side strips."

        def invoke(self, args: dict[str, Any]) -> str:
            return _create_axis_context_crop_tool(**args)

    create_axis_context_crop_tool = _FallbackAxisContextCropTool()
