from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image


LAB_ROOT = Path(__file__).resolve().parents[3]
DEERFLOW_ROOT = LAB_ROOT / "deer-flow"
BACKEND_ROOT = DEERFLOW_ROOT / "backend"


def _load_axis_module():
    module_path = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "tools" / "axis_grid_crop.py"
    spec = importlib.util.spec_from_file_location("axis_grid_crop_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_axis_context_crop_composes_main_crop_with_backfilled_strips(tmp_path):
    module = _load_axis_module()
    image_path = tmp_path / "grid.png"
    Image.new("RGB", (400, 300), "white").save(image_path)

    result = module.create_axis_context_crop(
        image_path=str(image_path),
        crop_bbox_px=[100, 90, 280, 220],
        axis_frame_bbox_px=[20, 30, 380, 280],
        output_dir=str(tmp_path / "out"),
        crop_id="grid_2B_5D",
        min_strip_px=40,
    )

    assert result["status"] == "pass"
    assert result["composed_size_px"] == {"width": 360, "height": 250}
    assert result["components"]["main"]["page_bbox_px"] == [100, 90, 280, 220]
    assert result["components"]["top_strip"]["page_bbox_px"] == [100, 30, 280, 90]
    assert result["components"]["bottom_strip"]["page_bbox_px"] == [100, 220, 280, 280]
    assert result["components"]["left_strip"]["page_bbox_px"] == [20, 90, 100, 220]
    assert result["components"]["right_strip"]["page_bbox_px"] == [280, 90, 380, 220]

    meta = json.loads(Path(result["meta_path"]).read_text(encoding="utf-8"))
    assert meta["axis_label_backfill"]["strategy"] == "side_strip_context"
    assert Path(result["image_path"]).is_file()


def test_axis_context_crop_accepts_mounted_gpt_pro_blueprint(tmp_path):
    module = _load_axis_module()

    result = module.create_axis_context_crop(
        image_path="/mnt/gpt-pro/CV_NotFunning_ReadAgent_Plan_v1/example_run/blueprints/PL-S-001.png",
        crop_bbox_px=[200, 300, 700, 1000],
        axis_frame_bbox_px=[0, 0, 1000, 1300],
        output_dir=str(tmp_path / "mounted"),
        crop_id="pl_s_001_probe",
        min_strip_px=96,
    )

    assert result["status"] == "pass"
    assert result["composed_size_px"] == {"width": 1000, "height": 1300}
    assert Path(result["image_path"]).is_file()


def test_config_routes_axis_context_crop_tool():
    config = (DEERFLOW_ROOT / "config.yaml").read_text(encoding="utf-8")
    skill = (
        LAB_ROOT / "prompt-workbench" / "skills" / "custom" / "civil-structural-plan" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "name: create_axis_context_crop" in config
    assert "group: civil:read_agent" in config
    assert "deerflow.tools.axis_grid_crop:create_axis_context_crop_tool" in config
    assert "create_axis_context_crop" in skill
    assert "axis_frame_bbox_px" in skill
