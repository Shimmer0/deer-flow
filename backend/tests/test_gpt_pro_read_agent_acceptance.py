from __future__ import annotations

import importlib.util
import json
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[3]
DEERFLOW_ROOT = LAB_ROOT / "deer-flow"
BACKEND_ROOT = DEERFLOW_ROOT / "backend"
GPT_PRO_PACKAGE = LAB_ROOT / "docs" / "GPT_PRO" / "CV_NotFunning_ReadAgent_Plan_v1"


def _load_module(relative_path: str, module_name: str):
    module_path = BACKEND_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_config_mounts_and_routes_gpt_pro_read_agent_tool():
    config = (DEERFLOW_ROOT / "config.yaml").read_text(encoding="utf-8")
    skill = (
        LAB_ROOT / "prompt-workbench" / "skills" / "custom" / "civil-structural-plan" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "/mnt/gpt-pro" in config
    assert "docs/GPT_PRO" in config
    assert "name: replicate_gpt_pro_example" in config
    assert "group: civil:read_agent" in config
    assert "deerflow.tools.gpt_pro_read_agent:replicate_gpt_pro_example_tool" in config
    assert "replicate_gpt_pro_example" in skill
    assert "/mnt/gpt-pro/CV_NotFunning_ReadAgent_Plan_v1/example_run" in skill
    assert (LAB_ROOT / "harness-workbench" / "scripts" / "run_gpt_pro_replay_acceptance.py").is_file()
    assert (LAB_ROOT / "harness-workbench" / "scripts" / "run_deerflow_fake_gpt_pro_replay_acceptance.py").is_file()


def test_python_script_tool_can_run_packaged_gpt_pro_validator():
    module = _load_module(
        "packages/harness/deerflow/tools/python_scripts.py",
        "python_scripts_under_test",
    )

    result = module.run_python_script_file(
        "/mnt/gpt-pro/CV_NotFunning_ReadAgent_Plan_v1/tools/python/run_pl_s_001_example.py",
        timeout_seconds=30,
    )

    assert result["exit_code"] == 0
    assert result["timed_out"] is False
    assert "Columns: 42" in result["stdout"]
    assert "Graph edges: 71" in result["stdout"]
    assert '"ok": true' in result["stdout"]


def test_replicate_gpt_pro_example_copies_artifacts_and_verifies_hashes(tmp_path):
    module = _load_module(
        "packages/harness/deerflow/tools/gpt_pro_read_agent.py",
        "gpt_pro_read_agent_under_test",
    )

    result = module.replicate_gpt_pro_example(
        example_id="PL-S-001",
        output_dir=str(tmp_path / "pl_s_001_replay"),
    )

    assert result["status"] == "pass"
    assert result["source_package"] == str(GPT_PRO_PACKAGE)
    assert result["file_count"] == 47
    assert result["hashes_match"] is True
    assert result["semantic_summary"] == {
        "blueprint_id": "PL-S-001",
        "grid_x_total_mm": 49200,
        "grid_y_total_mm": 41700,
        "columns": 42,
        "main_beams": 13,
        "graph_edges": 71,
        "stage1_quadrant_crops": 4,
        "stage2_axis_label_crops": 13,
        "stage3_detail_crops": 13,
    }
    assert result["axis_context"]["quadrant_count"] == 4
    assert result["axis_context"]["quadrants"]["crop_4F_7C"]["x_axis_labels"] == [
        "4",
        "5",
        "6",
        "7",
    ]
    assert result["axis_context"]["quadrants"]["crop_4F_7C"]["y_axis_labels"] == [
        "C",
        "D",
        "E",
        "F",
    ]

    replay_root = Path(result["output_dir"])
    report = json.loads((replay_root / "replication_report.json").read_text(encoding="utf-8"))
    copied_stage2 = replay_root / "example_run" / "outputs" / "stage2" / "PL-S-001_primary_structure_stage2.json"

    assert report["status"] == "pass"
    assert copied_stage2.is_file()
    assert (replay_root / "example_run" / "logs" / "tool_calls.jsonl").is_file()
