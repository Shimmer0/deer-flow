from __future__ import annotations

import json
import re
from typing import Any


_NUMERIC_AXIS_RE = re.compile(r"^[1-9][0-9]?$")
_ALPHA_AXIS_RE = re.compile(r"^[A-Z]{1,2}$")


def _items(value: list[dict[str, Any]] | str) -> list[dict[str, Any]]:
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise TypeError("OCR items must be a list")
    return [item for item in parsed if isinstance(item, dict)]


def _normalize_text(text: Any) -> str:
    normalized = str(text or "").strip().upper()
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = re.sub(r"^[○〇◎\s]+|[○〇◎\s]+$", "", normalized)
    return normalized


def _bbox(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None
    if len(value) == 4 and all(isinstance(v, (int, float)) for v in value):
        x0, y0, x1, y1 = [int(round(v)) for v in value]
        if x1 > x0 and y1 > y0:
            return [x0, y0, x1, y1]
        return None
    points: list[tuple[float, float]] = []
    for point in value:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = point[0], point[1]
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                points.append((float(x), float(y)))
    if len(points) >= 2:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [int(round(min(xs))), int(round(min(ys))), int(round(max(xs))), int(round(max(ys)))]
    return None


def _axis_family(label: str) -> str | None:
    if _NUMERIC_AXIS_RE.match(label):
        return "numeric"
    if _ALPHA_AXIS_RE.match(label):
        return "alpha"
    return None


def _center(item: dict[str, Any], bbox: list[int]) -> tuple[list[int], str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for source, payload in [
        ("metadata.axis_anchor_center", metadata.get("axis_anchor_center")),
        ("axis_anchor_center", item.get("axis_anchor_center")),
    ]:
        if (
            isinstance(payload, list)
            and len(payload) >= 2
            and isinstance(payload[0], (int, float))
            and isinstance(payload[1], (int, float))
        ):
            return [int(round(payload[0])), int(round(payload[1]))], source
    x0, y0, x1, y1 = bbox
    return [int(round((x0 + x1) / 2)), int(round((y0 + y1) / 2))], "bbox_center"


def _page_side(center: list[int], image_size_px: dict[str, Any] | None) -> str | None:
    if not image_size_px:
        return None
    width = int(image_size_px.get("width") or 0)
    height = int(image_size_px.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    x, y = center
    margin_x = width * 0.20
    margin_y = height * 0.20
    if y <= margin_y:
        return "top"
    if y >= height - margin_y:
        return "bottom"
    if x <= margin_x:
        return "left"
    if x >= width - margin_x:
        return "right"
    return "interior"


def _axis_sort_key(label: str) -> tuple[int, Any]:
    if _NUMERIC_AXIS_RE.match(label):
        return (0, int(label))
    return (1, label)


def detect_axis_labels_from_ocr(
    ocr_items: list[dict[str, Any]] | str,
    image_size_px: dict[str, Any] | None = None,
    min_confidence: float = 0.5,
) -> dict[str, Any]:
    """Detect axis labels and localization metadata from OCR items."""
    axis_labels: list[dict[str, Any]] = []
    ignored_count = 0

    for index, item in enumerate(_items(ocr_items)):
        confidence = float(item.get("confidence", item.get("score", 1.0)) or 0.0)
        text = _normalize_text(item.get("text", item.get("label", "")))
        bbox = _bbox(item.get("bbox_px", item.get("bbox")))
        family = _axis_family(text)
        if confidence < min_confidence or family is None or bbox is None:
            ignored_count += 1
            continue
        center, anchor_source = _center(item, bbox)
        axis_labels.append(
            {
                "label": text,
                "axis_family": family,
                "bbox_px": bbox,
                "center_px": center,
                "page_side": _page_side(center, image_size_px),
                "confidence": confidence,
                "source_index": index,
                "anchor_source": anchor_source,
            }
        )

    axis_labels.sort(key=lambda item: (_axis_sort_key(item["label"]), item["source_index"]))
    numeric_labels = [item["label"] for item in axis_labels if item["axis_family"] == "numeric"]
    alpha_labels = [item["label"] for item in axis_labels if item["axis_family"] == "alpha"]
    return {
        "status": "pass",
        "axis_labels": axis_labels,
        "numeric_axis_labels": numeric_labels,
        "alpha_axis_labels": alpha_labels,
        "ignored_count": ignored_count,
        "source_item_count": len(_items(ocr_items)),
    }


def _detect_axis_labels_tool(
    ocr_items: list[dict[str, Any]] | str,
    image_size_px: dict[str, Any] | None = None,
    min_confidence: float = 0.5,
) -> str:
    """Detect axis labels from OCR output items.

    Args:
        ocr_items: OCR items as a JSON list or list of objects with text, bbox, and confidence.
        image_size_px: Optional image size object with width and height.
        min_confidence: Minimum OCR confidence to accept.
    """
    return json.dumps(
        detect_axis_labels_from_ocr(
            ocr_items=ocr_items,
            image_size_px=image_size_px,
            min_confidence=min_confidence,
        ),
        ensure_ascii=False,
        sort_keys=True,
    )


try:
    from langchain.tools import tool

    detect_axis_labels_tool = tool("detect_axis_labels", parse_docstring=True)(_detect_axis_labels_tool)
except Exception:

    class _FallbackAxisLabelDetectionTool:
        name = "detect_axis_labels"
        description = "Detect axis labels from OCR output items."

        def invoke(self, args: dict[str, Any]) -> str:
            return _detect_axis_labels_tool(**args)

    detect_axis_labels_tool = _FallbackAxisLabelDetectionTool()
