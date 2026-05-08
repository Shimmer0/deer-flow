from __future__ import annotations

import hashlib
import json
import os
import posixpath
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


_GPT_PRO_CONTAINER_PATH = "/mnt/gpt-pro"
_HARNESS_CONTAINER_PATH = "/mnt/harness-workbench"
_DEFAULT_PACKAGE_RELATIVE = Path("docs") / "GPT_PRO" / "CV_NotFunning_ReadAgent_Plan_v1"
_MAX_VALIDATOR_SECONDS = 60


def _lab_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _package_root() -> Path:
    configured = os.environ.get("GPT_PRO_READ_AGENT_PACKAGE")
    package = Path(configured).expanduser().resolve() if configured else (_lab_root() / _DEFAULT_PACKAGE_RELATIVE).resolve()
    if not package.is_dir():
        raise FileNotFoundError(f"GPT_PRO read-agent package not found: {package}")
    return package


def _resolve_output_dir(output_dir: str | None, example_id: str) -> Path:
    root = _lab_root()
    if output_dir:
        normalized = posixpath.normpath(output_dir)
        if normalized == _HARNESS_CONTAINER_PATH or normalized.startswith(f"{_HARNESS_CONTAINER_PATH}/"):
            relative = normalized[len(_HARNESS_CONTAINER_PATH) :].lstrip("/")
            candidate = root / "harness-workbench" / relative
        else:
            candidate = Path(output_dir)
    else:
        candidate = root / "harness-workbench" / "gpt-pro-replays" / example_id

    resolved = candidate.expanduser().resolve()
    allowed_roots = [
        (root / "harness-workbench").resolve(),
        Path("/tmp").resolve(),
    ]
    for allowed_root in allowed_roots:
        try:
            resolved.relative_to(allowed_root)
            return resolved
        except ValueError:
            continue
    raise PermissionError("GPT_PRO replay output must be under /mnt/harness-workbench or /tmp")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            stat = path.stat()
            files[relative] = {
                "size": stat.st_size,
                "sha256": _sha256_file(path),
            }
    return files


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stage2_result(example_run: Path) -> dict[str, Any]:
    stage2 = _load_json(example_run / "outputs" / "stage2" / "PL-S-001_primary_structure_stage2.json")
    return stage2.get("stage2_primary_structure_result", stage2)


def _semantic_summary(example_run: Path) -> dict[str, Any]:
    stage1 = _load_json(example_run / "outputs" / "stage1" / "PL-S-001_layout_stage1.json")
    stage2 = _stage2_result(example_run)
    axis_label_dir = example_run / "agent_local_crops" / "PL-S-001" / "stage2_axis_and_labels"
    stage3_detail_dir = example_run / "agent_local_crops" / "PL-S-001" / "stage3_details"
    return {
        "blueprint_id": "PL-S-001",
        "grid_x_total_mm": stage2["grid"]["x_total_mm"],
        "grid_y_total_mm": stage2["grid"]["y_total_mm"],
        "columns": len(stage2["columns"]),
        "main_beams": len(stage2["main_beams"]),
        "graph_edges": len(stage2["graph"]["edges"]),
        "stage1_quadrant_crops": len([crop for crop in stage1["crops"] if crop.get("role") == "high_res_main_plan_quadrant"]),
        "stage2_axis_label_crops": len(list(axis_label_dir.glob("*.png"))),
        "stage3_detail_crops": len(list(stage3_detail_dir.glob("*.png"))),
    }


def _axis_context(example_run: Path) -> dict[str, Any]:
    stage1 = _load_json(example_run / "outputs" / "stage1" / "PL-S-001_layout_stage1.json")
    stage2 = _stage2_result(example_run)
    x_axes = {axis["label"]: axis for axis in stage2["grid"]["x_axes"]}
    y_axes = {axis["label"]: axis for axis in stage2["grid"]["y_axes"]}
    quadrants: dict[str, Any] = {}

    for crop in stage1["crops"]:
        if crop.get("role") != "high_res_main_plan_quadrant":
            continue
        coverage = crop.get("coverage_grid") or {}
        x_labels = list(coverage.get("x_axes") or [])
        y_labels = list(coverage.get("y_axes") or [])
        quadrants[crop["crop_id"]] = {
            "file_name": crop["file_name"],
            "x_axis_labels": x_labels,
            "y_axis_labels": y_labels,
            "x_axis_coords_mm": {label: x_axes[label]["coord_mm"] for label in x_labels if label in x_axes},
            "y_axis_coords_mm": {label: y_axes[label]["coord_mm"] for label in y_labels if label in y_axes},
            "backfill_policy": {
                "top_strip": {"axis_family": "x", "labels": x_labels},
                "bottom_strip": {"axis_family": "x", "labels": x_labels},
                "left_strip": {"axis_family": "y", "labels": y_labels},
                "right_strip": {"axis_family": "y", "labels": y_labels},
            },
        }

    return {
        "strategy": "grid-aware crop manifest with periphery axis-label backfill strips",
        "paddleocr_reference": "Inspired by PaddleOCR side-strip axis context: crop first, preserve cut-away axis labels as top/bottom/left/right context.",
        "quadrant_count": len(quadrants),
        "quadrants": quadrants,
    }


def _run_packaged_validator(package_root: Path) -> dict[str, Any]:
    script = package_root / "tools" / "python" / "run_pl_s_001_example.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(package_root),
        capture_output=True,
        text=True,
        timeout=_MAX_VALIDATOR_SECONDS,
        check=False,
    )
    return {
        "command": [sys.executable, str(script)],
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-12000:],
        "stderr": completed.stderr[-12000:],
    }


def replicate_gpt_pro_example(example_id: str = "PL-S-001", output_dir: str | None = None) -> dict[str, Any]:
    """Copy and verify the packaged GPT_PRO PL-S-001 example run."""
    if example_id != "PL-S-001":
        raise ValueError("Only PL-S-001 is packaged for GPT_PRO replication")

    package_root = _package_root()
    source_example = package_root / "example_run"
    if not source_example.is_dir():
        raise FileNotFoundError(f"Packaged example_run missing: {source_example}")

    replay_root = _resolve_output_dir(output_dir, example_id)
    replay_example = replay_root / "example_run"
    replay_root.mkdir(parents=True, exist_ok=True)
    if replay_example.exists():
        shutil.rmtree(replay_example)
    shutil.copytree(source_example, replay_example)

    source_manifest = _manifest(source_example)
    replay_manifest = _manifest(replay_example)
    hashes_match = source_manifest == replay_manifest
    validator = _run_packaged_validator(package_root)
    status = "pass" if hashes_match and validator["exit_code"] == 0 else "fail"
    summary = _semantic_summary(source_example)
    axis_context = _axis_context(source_example)

    report = {
        "status": status,
        "example_id": example_id,
        "source_package": str(package_root),
        "source_example_run": str(source_example),
        "output_dir": str(replay_root),
        "file_count": len(source_manifest),
        "hashes_match": hashes_match,
        "semantic_summary": summary,
        "axis_context": axis_context,
        "validator": validator,
        "source_manifest": source_manifest,
        "replay_manifest": replay_manifest,
    }
    (replay_root / "replication_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return report


def _replicate_gpt_pro_example_tool(example_id: str = "PL-S-001", output_dir: str | None = None) -> str:
    """Replicate the packaged GPT_PRO engineering drawing example_run.

    Args:
        example_id: Packaged example id. Only PL-S-001 is available.
        output_dir: Optional replay output directory under /mnt/harness-workbench.
    """
    result = replicate_gpt_pro_example(example_id=example_id, output_dir=output_dir)
    public_result = {
        key: value
        for key, value in result.items()
        if key not in {"source_manifest", "replay_manifest"}
    }
    return json.dumps(public_result, ensure_ascii=False, sort_keys=True)


try:
    from langchain.tools import tool

    replicate_gpt_pro_example_tool = tool("replicate_gpt_pro_example", parse_docstring=True)(_replicate_gpt_pro_example_tool)
except Exception:

    class _FallbackGptProReadAgentTool:
        name = "replicate_gpt_pro_example"
        description = "Replicate the packaged GPT_PRO engineering drawing example_run."

        def invoke(self, args: dict[str, Any]) -> str:
            return _replicate_gpt_pro_example_tool(**args)

    replicate_gpt_pro_example_tool = _FallbackGptProReadAgentTool()
