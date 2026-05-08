from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path


LAB_ROOT = Path("/mnt/e/deerflow-agent-lab")
DEERFLOW_ROOT = LAB_ROOT / "deer-flow"
BACKEND_ROOT = DEERFLOW_ROOT / "backend"
PROMPT_WORKBENCH = LAB_ROOT / "prompt-workbench"
HARNESS_WORKBENCH = LAB_ROOT / "harness-workbench"
FIXTURE = HARNESS_WORKBENCH / "acceptance" / "civil-plan-frame-a.svg"
EXPECTED = HARNESS_WORKBENCH / "acceptance" / "civil-plan-frame-a.expected.json"


def test_prompt_and_harness_workbenches_are_planned():
    assert (PROMPT_WORKBENCH / "README.md").is_file()
    assert (PROMPT_WORKBENCH / "skills" / "custom" / "civil-structural-plan" / "SKILL.md").is_file()
    assert (PROMPT_WORKBENCH / "prompts" / "civil-plan-recognition.md").is_file()
    assert (PROMPT_WORKBENCH / "prompts" / "tool-orchestration-procedure.md").is_file()
    assert (HARNESS_WORKBENCH / "README.md").is_file()
    assert (HARNESS_WORKBENCH / "acceptance" / "civil-plan-acceptance.prompt.md").is_file()
    assert (HARNESS_WORKBENCH / "acceptance" / "completion-audit.md").is_file()
    assert (HARNESS_WORKBENCH / "acceptance" / "live-acceptance-result.md").is_file()
    assert (HARNESS_WORKBENCH / "acceptance" / "live-python-script-result.md").is_file()
    assert (HARNESS_WORKBENCH / "scripts" / "run_deerflow_live_agent_acceptance.py").is_file()
    assert (HARNESS_WORKBENCH / "scripts" / "run_deerflow_live_python_script_acceptance.py").is_file()
    assert (LAB_ROOT / "scripts" / "load-root-env.sh").is_file()
    assert (LAB_ROOT / "scripts" / "sync-root-env-to-deerflow-env.sh").is_file()
    assert (PROMPT_WORKBENCH / "config-notes" / "root-env-migration.md").is_file()


def test_deerflow_config_wires_civil_plan_tool_and_workbenches():
    config = (DEERFLOW_ROOT / "config.yaml").read_text(encoding="utf-8")

    assert "name: civil:plan" in config
    assert "name: python:script" in config
    assert "name: root-anthropic" in config
    assert "use: langchain_anthropic:ChatAnthropic" in config
    assert "anthropic_api_key: $ANTHROPIC_AUTH_TOKEN" in config
    assert "use: deerflow.tools.civil_plan:analyze_civil_plan_tool" in config
    assert "use: deerflow.tools.python_scripts:run_python_script_tool" in config
    assert f"path: {PROMPT_WORKBENCH / 'skills'}" in config
    assert f"host_path: {PROMPT_WORKBENCH}" in config
    assert "container_path: /mnt/prompt-workbench" in config
    assert f"host_path: {HARNESS_WORKBENCH}" in config
    assert "container_path: /mnt/harness-workbench" in config


def test_civil_plan_prompt_requires_tool_first():
    skill = (PROMPT_WORKBENCH / "skills" / "custom" / "civil-structural-plan" / "SKILL.md").read_text(encoding="utf-8")
    prompt = (PROMPT_WORKBENCH / "prompts" / "civil-plan-recognition.md").read_text(encoding="utf-8")

    assert "analyze_civil_plan" in skill
    assert "先调用" in skill
    assert "analyze_civil_plan" in prompt
    assert "/mnt/harness-workbench/acceptance/civil-plan-frame-a.svg" in prompt


def test_civil_plan_tool_analyzes_acceptance_fixture():
    module_path = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "tools" / "civil_plan.py"
    spec = importlib.util.spec_from_file_location("civil_plan_tool_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))

    result = module.analyze_civil_plan_file(str(FIXTURE))

    assert result["drawing_id"] == expected["drawing_id"]
    assert result["column_count"] == expected["column_count"]
    assert result["beam_count"] == expected["beam_count"]
    assert result["max_beam_span_m"] == expected["max_beam_span_m"]
    assert result["floor_area_m2"] == expected["floor_area_m2"]
    assert result["total_vertical_load_kN"] == expected["total_vertical_load_kN"]
    assert result["answer"] == expected["answer"]


def test_python_script_tool_runs_whitelisted_harness_script():
    module_path = BACKEND_ROOT / "packages" / "harness" / "deerflow" / "tools" / "python_scripts.py"
    spec = importlib.util.spec_from_file_location("python_script_tool_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    result = module.run_python_script_file(
        "/mnt/harness-workbench/scripts/civil_plan_python_probe.py",
        args=["--drawing", "/mnt/harness-workbench/acceptance/civil-plan-frame-a.svg"],
    )

    assert result["exit_code"] == 0
    assert result["timed_out"] is False
    assert '"column_count": 9' in result["stdout"]
    assert '"beam_count": 12' in result["stdout"]

    tool_result = json.loads(
        module._run_python_script_tool(
            "/mnt/harness-workbench/scripts/civil_plan_python_probe.py",
            script_args=json.dumps(["--drawing", "/mnt/harness-workbench/acceptance/civil-plan-frame-a.svg"]),
        )
    )
    assert tool_result["exit_code"] == 0
    assert '"total_vertical_load_kN": 528.0' in tool_result["stdout"]
