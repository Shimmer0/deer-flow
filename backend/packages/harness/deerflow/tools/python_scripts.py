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
_GPT_PRO_CONTAINER_PATH = "/mnt/gpt-pro"
_MAX_TIMEOUT_SECONDS = 60
_MAX_OUTPUT_CHARS = 12000

_SECRET_REDACTION_PATTERNS = [
    ("OPENAI_API_KEY", "OPENAI_API_KEY=<redacted>"),
    ("READ_AGENT_LLM_API_KEY", "READ_AGENT_LLM_API_KEY=<redacted>"),
    ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY=<redacted>"),
]


def _host_python_enabled() -> bool:
    return os.environ.get("DEER_FLOW_ALLOW_HOST_PYTHON_SCRIPTS", "").lower() in {"1", "true", "yes"}


def _allowlist() -> set[str]:
    raw = os.environ.get("DEER_FLOW_PYTHON_SCRIPT_ALLOWLIST", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _script_allowed(script_path: str, resolved_script: Path) -> bool:
    allowed = _allowlist()
    if not allowed:
        return False
    normalized_request = posixpath.normpath(script_path)
    resolved_text = str(resolved_script.resolve())
    return normalized_request in allowed or resolved_text in allowed or resolved_script.name in allowed


def _scrub_env() -> dict[str, str]:
    # Deliberately do not pass the parent process environment. This prevents
    # Agent-authored scripts from reading API tokens, cookies, or DB credentials.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(_backend_root()),
    }
    if os.environ.get("DEER_FLOW_CONFIG_PATH_SAFE"):
        env["DEER_FLOW_CONFIG_PATH"] = os.environ["DEER_FLOW_CONFIG_PATH_SAFE"]
    return env


def _redact(text: str) -> str:
    redacted = text
    for name, replacement in _SECRET_REDACTION_PATTERNS:
        value = os.environ.get(name)
        if value:
            redacted = redacted.replace(value, "<redacted>")
        redacted = redacted.replace(f"{name}=", replacement + " # ")
    return redacted


def _lab_root() -> Path:
    return Path(__file__).resolve().parents[6]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _venv_python() -> str:
    configured = os.getenv("DEER_FLOW_PYTHON_INTERPRETER")
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.exists():
            raise FileNotFoundError(f"Configured Python interpreter not found: {configured}")
        return str(candidate)

    candidate = _lab_root() / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _allowed_mounts() -> list[tuple[str, Path]]:
    root = _lab_root()
    mounts = [
        (_HARNESS_CONTAINER_PATH, root / "harness-workbench"),
        (_PROMPT_CONTAINER_PATH, root / "prompt-workbench"),
        (_GPT_PRO_CONTAINER_PATH, root / "docs" / "GPT_PRO"),
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

    raise PermissionError("Python script path must be under /mnt/harness-workbench, /mnt/prompt-workbench, or /mnt/gpt-pro")


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
    """Run a strictly allowlisted Python script from the lab workbenches.

    Production default is deny. Enable only in a sandbox with:
    DEER_FLOW_ALLOW_HOST_PYTHON_SCRIPTS=true
    DEER_FLOW_PYTHON_SCRIPT_ALLOWLIST=/absolute/script.py,/mnt/harness-workbench/tool.py
    """
    if not _host_python_enabled():
        raise PermissionError("run_python_script is disabled by default. Set DEER_FLOW_ALLOW_HOST_PYTHON_SCRIPTS=true in a sandbox to enable it.")
    resolved_script = _resolve_script_path(script_path)
    if not _script_allowed(script_path, resolved_script):
        raise PermissionError("Python script is not in DEER_FLOW_PYTHON_SCRIPT_ALLOWLIST")
    safe_args = _safe_args(args)
    timeout = max(1, min(int(timeout_seconds), _MAX_TIMEOUT_SECONDS))
    env = _scrub_env()

    command = [_venv_python(), str(resolved_script), *safe_args]
    try:
        completed = subprocess.run(
            command,
            cwd=str(resolved_script.parent),
            env=env,
            text=True,
            capture_output=True,
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
        "stdout": _redact(stdout)[-_MAX_OUTPUT_CHARS:],
        "stderr": _redact(stderr)[-_MAX_OUTPUT_CHARS:],
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
