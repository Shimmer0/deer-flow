from __future__ import annotations

import importlib.util
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[3]
DEERFLOW_ROOT = LAB_ROOT / "deer-flow"
BACKEND_ROOT = DEERFLOW_ROOT / "backend"


def _load_axis_module():
    module_path = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "tools" / "axis_label_detection.py"
    spec = importlib.util.spec_from_file_location("axis_label_detection_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detect_axis_labels_from_ocr_items_filters_structural_marks():
    module = _load_axis_module()

    result = module.detect_axis_labels_from_ocr(
        [
            {"text": "1", "bbox": [10, 20, 34, 44], "confidence": 0.98},
            {"text": "2", "bbox": [110, 20, 134, 44], "confidence": 0.96},
            {"text": "A", "bbox": [6, 200, 30, 224], "confidence": 0.95},
            {"text": "B", "bbox": [6, 310, 30, 334], "confidence": 0.94},
            {"text": "KL10(3)", "bbox": [100, 100, 190, 130], "confidence": 0.99},
            {"text": "C", "bbox": [8, 410, 30, 434], "confidence": 0.30},
        ],
        image_size_px={"width": 500, "height": 600},
        min_confidence=0.5,
    )

    assert result["status"] == "pass"
    assert [item["label"] for item in result["axis_labels"]] == ["1", "2", "A", "B"]
    assert result["numeric_axis_labels"] == ["1", "2"]
    assert result["alpha_axis_labels"] == ["A", "B"]
    assert result["axis_labels"][0]["center_px"] == [22, 32]
    assert result["ignored_count"] == 2


def test_detect_axis_labels_uses_anchor_metadata_and_quadrilateral_bbox():
    module = _load_axis_module()

    result = module.detect_axis_labels_from_ocr(
        [
            {
                "text": "3",
                "bbox": [[100, 10], [130, 12], [128, 42], [98, 39]],
                "confidence": 0.91,
                "metadata": {"axis_anchor_center": [120, 25], "axis_anchor_radius": 16},
            }
        ],
        image_size_px={"width": 400, "height": 400},
    )

    assert result["axis_labels"][0]["bbox_px"] == [98, 10, 130, 42]
    assert result["axis_labels"][0]["center_px"] == [120, 25]
    assert result["axis_labels"][0]["anchor_source"] == "metadata.axis_anchor_center"


def test_config_routes_axis_label_detection_tool():
    config = (DEERFLOW_ROOT / "config.yaml").read_text(encoding="utf-8")
    skill = (
        LAB_ROOT / "prompt-workbench" / "skills" / "custom" / "civil-structural-plan" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "name: detect_axis_labels" in config
    assert "deerflow.tools.axis_label_detection:detect_axis_labels_tool" in config
    assert "detect_axis_labels" in skill
