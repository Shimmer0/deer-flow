from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from PIL import Image


LAB_ROOT = Path(__file__).resolve().parents[3]
DEERFLOW_ROOT = LAB_ROOT / "deer-flow"
BACKEND_ROOT = DEERFLOW_ROOT / "backend"


def _load_paddleocr_module():
    module_path = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "tools" / "paddleocr_client.py"
    spec = importlib.util.spec_from_file_location("paddleocr_client_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_axis_label_module():
    module_path = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "tools" / "axis_label_detection.py"
    spec = importlib.util.spec_from_file_location("axis_label_detection_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeOcrRuntime:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                runtime.requests.append({"path": self.path, "payload": payload})
                body = json.dumps(runtime.response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "_FakeOcrRuntime":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _png(path: Path, size: tuple[int, int] = (120, 80)) -> Path:
    Image.new("RGB", size, "white").save(path)
    return path


def test_recognize_sheet_text_posts_full_page_to_local_runtime(tmp_path: Path) -> None:
    module = _load_paddleocr_module()
    image = _png(tmp_path / "sheet.png")
    response = {
        "ok": True,
        "backend": "paddle_local_server",
        "text_units": [
            {"text": "二层结构平面图", "confidence": 0.92, "bbox": [10, 20, 110, 40], "bbox_space": "image"}
        ],
        "metadata": {"profile": "fake"},
    }

    with _FakeOcrRuntime(response) as runtime:
        result = module.recognize_sheet_text(
            str(image),
            endpoint=runtime.endpoint,
            ocr_config_override={"text_detection_model_name": "PP-OCRv5_mobile_det"},
        )

    assert result["status"] == "pass"
    assert result["mode"] == "full_page"
    assert result["backend"] == "paddle_local_server"
    assert result["text_unit_count"] == 1
    assert result["text_units"][0]["text"] == "二层结构平面图"
    assert runtime.requests[0]["path"] == "/v1/ocr/images"
    assert runtime.requests[0]["payload"]["image_paths"] == [str(image.resolve())]
    assert runtime.requests[0]["payload"]["ocr_config_override"]["text_detection_model_name"] == "PP-OCRv5_mobile_det"


def test_recognize_sheet_text_posts_regions_and_preserves_region_ids(tmp_path: Path) -> None:
    module = _load_paddleocr_module()
    image = _png(tmp_path / "sheet.png")
    response = {
        "ok": True,
        "backend": "paddle_local_server_regions",
        "text_units": [
            {
                "text": "六层结构平面图",
                "confidence": 0.88,
                "bbox": [100, 3000, 260, 3040],
                "bbox_space": "original",
                "source_region_id": "title_001",
            }
        ],
    }

    with _FakeOcrRuntime(response) as runtime:
        result = module.recognize_sheet_text(
            str(image),
            endpoint=runtime.endpoint,
            regions=[{"region_id": "title_001", "bbox": [90, 2990, 280, 3060], "region_type": "drawing_title"}],
        )

    assert result["status"] == "pass"
    assert result["mode"] == "regions"
    assert result["text_units"][0]["source_region_id"] == "title_001"
    assert runtime.requests[0]["path"] == "/v1/ocr/regions"
    assert runtime.requests[0]["payload"]["regions"][0]["region_id"] == "title_001"


def test_recognize_sheet_text_output_feeds_axis_label_detection(tmp_path: Path) -> None:
    paddleocr = _load_paddleocr_module()
    axis_labels = _load_axis_label_module()
    image = _png(tmp_path / "sheet.png", size=(400, 300))
    response = {
        "ok": True,
        "backend": "paddle_local_server",
        "text_units": [
            {"text": "A", "confidence": 0.91, "bbox": [10, 180, 40, 210], "bbox_space": "image"},
            {"text": "1", "confidence": 0.93, "bbox": [300, 10, 330, 40], "bbox_space": "image"},
            {"text": "02020 20", "confidence": 0.31, "bbox": [220, 90, 280, 140], "bbox_space": "image"},
        ],
    }

    with _FakeOcrRuntime(response) as runtime:
        result = paddleocr.recognize_sheet_text(str(image), endpoint=runtime.endpoint)

    detected = axis_labels.detect_axis_labels_from_ocr(
        result["text_units"],
        image_size_px={"width": 400, "height": 300},
    )

    assert detected["numeric_axis_labels"] == ["1"]
    assert detected["alpha_axis_labels"] == ["A"]
    assert detected["ignored_count"] == 1


def test_recognize_sheet_text_marks_axis_label_ocr_for_review(tmp_path: Path) -> None:
    module = _load_paddleocr_module()
    image = _png(tmp_path / "sheet.png")
    response = {
        "ok": True,
        "backend": "paddle_local_server",
        "text_units": [
            {"text": "-", "confidence": 0.53, "bbox": [10, 20, 30, 40], "bbox_space": "image"},
            {"text": "02020 20", "confidence": 0.31, "bbox": [50, 20, 110, 40], "bbox_space": "image"},
        ],
    }

    with _FakeOcrRuntime(response) as runtime:
        result = module.recognize_sheet_text(
            str(image),
            endpoint=runtime.endpoint,
            expected_content="axis_labels",
            min_confidence=0.5,
        )

    assert result["status"] == "review"
    assert result["quality_summary"]["axis_label_candidate_count"] == 0
    assert result["quality_summary"]["low_confidence_count"] == 1
    assert "no_axis_label_candidates" in result["quality_summary"]["warnings"]


def test_recognize_sheet_text_rejects_container_path_escape(tmp_path: Path) -> None:
    module = _load_paddleocr_module()
    _png(tmp_path / "sheet.png")

    with pytest.raises(PermissionError, match="Image path must be under"):
        module.recognize_sheet_text("/mnt/gpt-pro/../sheet.png", endpoint="http://127.0.0.1:8765")


def test_recognize_sheet_text_rejects_endpoint_path_or_query(tmp_path: Path) -> None:
    module = _load_paddleocr_module()
    image = _png(tmp_path / "sheet.png")

    with pytest.raises(ValueError, match="bare local origin"):
        module.recognize_sheet_text(str(image), endpoint="http://127.0.0.1:8765/ocr?x=1")


def test_recognize_sheet_text_rejects_non_local_endpoint(tmp_path: Path) -> None:
    module = _load_paddleocr_module()
    image = _png(tmp_path / "sheet.png")

    with pytest.raises(PermissionError, match="local PaddleOCR endpoint"):
        module.recognize_sheet_text(str(image), endpoint="https://example.com/ocr")


def test_config_routes_paddleocr_tool_and_skill() -> None:
    config = (DEERFLOW_ROOT / "config.yaml").read_text(encoding="utf-8")
    skill = (
        LAB_ROOT / "prompt-workbench" / "skills" / "custom" / "civil-structural-plan" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "name: recognize_sheet_text" in config
    assert "deerflow.tools.paddleocr_client:recognize_sheet_text_tool" in config
    assert "recognize_sheet_text" in skill
