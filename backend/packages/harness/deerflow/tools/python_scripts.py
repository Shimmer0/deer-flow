from __future__ import annotations

import json
import os
import posixpath
import subprocess
import sys
from pathlib import Path
from typing import Any


_HARNESS_CONTAINER_PATH = "/mnt/harness-workbench"
_PROMPT_CONTAINER_PATH = "/mnt/prompt-workbench"
_MAX_TIMEOUT_SECONDS = 60
_MAX_OUTPUT_CHARS = 12000


def _lab_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _venv_python() -> str:
    candidate = _lab_root() / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _allowed_mounts() -> list[tuple[str, Path]]:
    root = _lab_root()
    mounts = [
        (_HARNESS_CONTAINER_PATH, root / "harness-workbench"),
        (_PROMPT_CONTAINER_PATH, root / "prompt-workbench"),
    ]
    try:
        from deerflow.config import get_app_config

        configured = []
        for mount in get_app_config().sandbox.mounts:
            host_path = Path(mount.host_path)
            if host_path.exists():
                configured.append((mount.container_path.rstrip("/"), host_path))
        for container_path, host_path in configured:
            if all(container_path != existing for existing, _ in mounts):
                mounts.append((container_path, host_path))
    except Exception:
        pass
    return mounts


def _resolve_script_path(script_path: str) -> Path:
    normalized = posixpath.normpath(script_path)
    for container_path, host_path in _allowed_mounts():
        if normalized == container_path or normalized.startswith(f"{container_path}/"):
            relative = normalized[len(container_path) :].lstrip("/")
            candidate = (host_path / relative).resolve()
            candidate.relative_to(host_path.resolve())
            if candidate.suffix != ".py":
                raise PermissionError("Only .py scripts are allowed")
            if not candidate.exists():
                raise FileNotFoundError(f"Python script not found: {script_path}")
            return candidate

    candidate = Path(script_path).resolve()
    for _, host_path in _allowed_mounts():
        try:
            candidate.relative_to(host_path.resolve())
        except ValueError:
            continue
        if candidate.suffix != ".py":
            raise PermissionError("Only .py scripts are allowed")
        if not candidate.exists():
            raise FileNotFoundError(f"Python script not found: {script_path}")
        return candidate

    raise PermissionError("Python script path must be under /mnt/harness-workbench or /mnt/prompt-workbench")


def _safe_args(args: list[str] | str | None) -> list[str]:
    if args is None:
        return []
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError as exc:
            raise TypeError("Script arguments string must be a JSON list of strings") from exc
        args = parsed
    if not isinstance(args, list):
        raise TypeError("Script arguments must be a list of strings")
    if len(args) > 32:
        raise ValueError("Too many script arguments")
    safe: list[str] = []
    for arg in args:
        if not isinstance(arg, str):
            raise TypeError("Script arguments must be strings")
        if "\x00" in arg:
            raise ValueError("NUL bytes are not allowed in script arguments")
        safe.append(arg)
    return safe


def run_python_script_file(script_path: str, args: list[str] | str | None = None, timeout_seconds: int = 30) -> dict[str, Any]:
    """Run a whitelisted Python script from the lab workbenches."""
    resolved_script = _resolve_script_path(script_path)
    safe_args = _safe_args(args)
    timeout = max(1, min(int(timeout_seconds), _MAX_TIMEOUT_SECONDS))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_backend_root())
    env.setdefault("DEER_FLOW_CONFIG_PATH", str(_lab_root() / "deer-flow" / "config.yaml"))

    command = [_venv_python(), str(resolved_script), *safe_args]
    try:
        completed = subprocess.run(
            command,
            cwd=str(resolved_script.parent),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        timed_out = False
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or "Python script timed out"

    return {
        "script_path": script_path,
        "resolved_path": str(resolved_script),
        "python": command[0],
        "args": safe_args,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "stdout": stdout[-_MAX_OUTPUT_CHARS:],
        "stderr": stderr[-_MAX_OUTPUT_CHARS:],
    }


def _run_python_script_tool(script_path: str, script_args: list[str] | str | None = None, timeout_seconds: int = 30) -> str:
    """Run a whitelisted Python script from the lab workbenches.

    Args:
        script_path: Python script path under /mnt/harness-workbench or /mnt/prompt-workbench.
        script_args: Optional list of string arguments to pass to the script. A JSON encoded string list is also accepted.
        timeout_seconds: Maximum runtime in seconds, capped at 60.
    """
    return json.dumps(run_python_script_file(script_path, args=script_args, timeout_seconds=timeout_seconds), ensure_ascii=False, sort_keys=True)


try:
    from langchain.tools import tool

    run_python_script_tool = tool("run_python_script", parse_docstring=True)(_run_python_script_tool)
except Exception:

    class _FallbackPythonScriptTool:
        name = "run_python_script"
        description = "Run a whitelisted Python script from the lab workbenches."

        def invoke(self, args: dict[str, Any]) -> str:
            return _run_python_script_tool(**args)

    run_python_script_tool = _FallbackPythonScriptTool()
