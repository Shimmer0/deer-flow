from __future__ import annotations

import json
import os
import posixpath
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_HARNESS_CONTAINER_PATH = "/mnt/harness-workbench"
_GPT_PRO_CONTAINER_PATH = "/mnt/gpt-pro"
_DEFAULT_ENDPOINT = "http://127.0.0.1:8765"
_MAX_TIMEOUT_SECONDS = 900.0


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


def _resolve_endpoint(endpoint: str | None) -> str:
    raw = (endpoint or os.environ.get("PADDLEOCR_ENDPOINT") or _DEFAULT_ENDPOINT).strip().rstrip("/")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise PermissionError("OCR requests are limited to a local PaddleOCR endpoint")
    if parsed.port is None:
        raise ValueError("PaddleOCR endpoint must include an explicit port")
    return raw


def _timeout(value: float | int) -> float:
    seconds = float(value)
    if seconds <= 0 or seconds > _MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be between 0 and {_MAX_TIMEOUT_SECONDS}")
    return seconds


def _json_obj(value: dict[str, Any] | str | None, name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    return parsed


def _regions(value: list[dict[str, Any]] | str | None) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        raise ValueError("regions must be a JSON array")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"regions[{index}] must be an object")
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(f"regions[{index}].bbox must be [x0, y0, x1, y1]")
        x0, y0, x1, y1 = [float(part) for part in bbox]
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"regions[{index}].bbox must have positive width and height")
        normalized.append(
            {
                "region_id": str(item.get("region_id") or f"region_{index:04d}"),
                "bbox": [x0, y0, x1, y1],
                "bbox_space": str(item.get("bbox_space") or "original"),
                "region_type": str(item.get("region_type") or "ocr_region"),
            }
        )
    return normalized


def _post_json(endpoint: str, route: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{endpoint}{route}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        raise ConnectionError(f"PaddleOCR local endpoint request failed: {error}") from error
    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise ValueError("PaddleOCR response must be a JSON object")
    return decoded


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        return [float(part) for part in value]
    except (TypeError, ValueError):
        return None


def _normalize_text_units(units: Any, *, image_path: str) -> list[dict[str, Any]]:
    if not isinstance(units, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            continue
        text = str(unit.get("text") or "").strip()
        if not text:
            continue
        payload: dict[str, Any] = {
            "unit_id": str(unit.get("unit_id") or f"ocr_{len(normalized):06d}"),
            "text": text,
            "confidence": _float_or_none(unit.get("confidence")),
            "bbox": _bbox(unit.get("bbox")),
            "bbox_space": str(unit.get("bbox_space") or "image"),
            "image_path": image_path,
            "metadata": dict(unit.get("metadata") or {}),
        }
        if unit.get("source_region_id") is not None:
            payload["source_region_id"] = str(unit["source_region_id"])
        payload["metadata"]["source_text_index"] = unit.get("metadata", {}).get("source_text_index", index)
        normalized.append(payload)
    return normalized


def recognize_sheet_text(
    image_path: str,
    regions: list[dict[str, Any]] | str | None = None,
    endpoint: str | None = None,
    ocr_config_override: dict[str, Any] | str | None = None,
    include_text_units: bool = True,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    """Recognize drawing text through a local PaddleOCR runtime endpoint."""
    resolved_image = _resolve_input_path(image_path)
    resolved_endpoint = _resolve_endpoint(endpoint)
    timeout = _timeout(timeout_seconds)
    normalized_regions = _regions(regions)
    override = _json_obj(ocr_config_override, "ocr_config_override")

    if normalized_regions:
        route = "/v1/ocr/regions"
        mode = "regions"
        payload = {
            "image_path": str(resolved_image),
            "regions": normalized_regions,
            "include_text_units": include_text_units,
        }
    else:
        route = "/v1/ocr/images"
        mode = "full_page"
        payload = {
            "image_paths": [str(resolved_image)],
            "include_text_units": include_text_units,
        }
    if override is not None:
        payload["ocr_config_override"] = override

    response = _post_json(resolved_endpoint, route, payload, timeout)
    text_units = _normalize_text_units(response.get("text_units", []), image_path=image_path)
    ok = bool(response.get("ok", True))
    return {
        "status": "pass" if ok else "fail",
        "tool": "recognize_sheet_text",
        "mode": mode,
        "backend": response.get("backend"),
        "image_path": image_path,
        "endpoint": resolved_endpoint,
        "text_unit_count": len(text_units),
        "text_units": text_units,
        "runtime_metadata": response.get("metadata", {}),
        "runtime_profile": response.get("profile", {}),
        "raw_result_count": response.get("result_count"),
    }


def _recognize_sheet_text_tool(
    image_path: str,
    regions: list[dict[str, Any]] | str | None = None,
    endpoint: str | None = None,
    ocr_config_override: dict[str, Any] | str | None = None,
    include_text_units: bool = True,
    timeout_seconds: float = 600.0,
) -> str:
    """Recognize drawing text via local PaddleOCR runtime.

    Args:
        image_path: Image path under /mnt/harness-workbench, /mnt/gpt-pro, or /tmp.
        regions: Optional OCR regions. Each region has region_id, bbox [x0, y0, x1, y1], bbox_space, and region_type.
        endpoint: Local PaddleOCR endpoint. Defaults to PADDLEOCR_ENDPOINT or http://127.0.0.1:8765.
        ocr_config_override: Optional PaddleOCR runtime config override.
        include_text_units: Include normalized text units in the response.
        timeout_seconds: HTTP request timeout, max 900 seconds.
    """
    result = recognize_sheet_text(
        image_path=image_path,
        regions=regions,
        endpoint=endpoint,
        ocr_config_override=ocr_config_override,
        include_text_units=include_text_units,
        timeout_seconds=timeout_seconds,
    )
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


try:
    from langchain.tools import tool

    recognize_sheet_text_tool = tool("recognize_sheet_text", parse_docstring=True)(_recognize_sheet_text_tool)
except Exception:

    class _FallbackPaddleOcrClientTool:
        name = "recognize_sheet_text"
        description = "Recognize drawing text via local PaddleOCR runtime."

        def invoke(self, args: dict[str, Any]) -> str:
            return _recognize_sheet_text_tool(**args)

    recognize_sheet_text_tool = _FallbackPaddleOcrClientTool()
