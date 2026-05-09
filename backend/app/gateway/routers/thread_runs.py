"""Runs endpoints — create, stream, wait, cancel.

Implements the LangGraph Platform runs API on top of
:class:`deerflow.agents.runs.RunManager` and
:class:`deerflow.agents.stream_bridge.StreamBridge`.

SSE format is aligned with the LangGraph Platform protocol so that
the ``useStream`` React hook from ``@langchain/langgraph-sdk/react``
works without modification.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import mimetypes
import struct
import zipfile
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_checkpointer, get_current_user, get_feedback_repo, get_run_event_store, get_run_manager, get_run_store, get_stream_bridge
from app.gateway.services import sse_consumer, start_run
from deerflow.config.paths import get_paths
from deerflow.runtime import RunRecord, serialize_channel_values

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/threads", tags=["runs"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RunCreateRequest(BaseModel):
    assistant_id: str | None = Field(default=None, description="Agent / assistant to use")
    input: dict[str, Any] | None = Field(default=None, description="Graph input (e.g. {messages: [...]})")
    command: dict[str, Any] | None = Field(default=None, description="LangGraph Command")
    metadata: dict[str, Any] | None = Field(default=None, description="Run metadata")
    config: dict[str, Any] | None = Field(default=None, description="RunnableConfig overrides")
    context: dict[str, Any] | None = Field(default=None, description="DeerFlow context overrides (model_name, thinking_enabled, etc.)")
    webhook: str | None = Field(default=None, description="Completion callback URL")
    checkpoint_id: str | None = Field(default=None, description="Resume from checkpoint")
    checkpoint: dict[str, Any] | None = Field(default=None, description="Full checkpoint object")
    interrupt_before: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt before")
    interrupt_after: list[str] | Literal["*"] | None = Field(default=None, description="Nodes to interrupt after")
    stream_mode: list[str] | str | None = Field(default=None, description="Stream mode(s)")
    stream_subgraphs: bool = Field(default=False, description="Include subgraph events")
    stream_resumable: bool | None = Field(default=None, description="SSE resumable mode")
    on_disconnect: Literal["cancel", "continue"] = Field(default="cancel", description="Behaviour on SSE disconnect")
    on_completion: Literal["delete", "keep"] = Field(default="keep", description="Delete temp thread on completion")
    multitask_strategy: Literal["reject", "rollback", "interrupt", "enqueue"] = Field(default="reject", description="Concurrency strategy")
    after_seconds: float | None = Field(default=None, description="Delayed execution")
    if_not_exists: Literal["reject", "create"] = Field(default="create", description="Thread creation policy")
    feedback_keys: list[str] | None = Field(default=None, description="LangSmith feedback keys")


class RunResponse(BaseModel):
    run_id: str
    thread_id: str
    assistant_id: str | None = None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    multitask_strategy: str = "reject"
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_to_response(record: RunRecord) -> RunResponse:
    return RunResponse(
        run_id=record.run_id,
        thread_id=record.thread_id,
        assistant_id=record.assistant_id,
        status=record.status.value,
        metadata=record.metadata,
        kwargs=record.kwargs,
        multitask_strategy=record.multitask_strategy,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


_HIDDEN_CHAIN_OF_THOUGHT_KEYS = frozenset(
    {
        "chain_of_thought",
        "cot",
        "hidden_cot",
        "reasoning",
        "reasoning_content",
        "thinking",
        "thinking_blocks",
        "thought",
        "thoughts",
    }
)


def _hidden_chain_of_thought_redaction() -> dict[str, Any]:
    return {
        "redacted": True,
        "reason": "hidden_chain_of_thought",
    }


def _thread_virtual_path_roots(thread_id: str, user_id: str | None) -> list[tuple[str, str]]:
    paths = get_paths()
    roots = {
        "workspace": paths.sandbox_work_dir(thread_id, user_id=user_id),
        "uploads": paths.sandbox_uploads_dir(thread_id, user_id=user_id),
        "outputs": paths.sandbox_outputs_dir(thread_id, user_id=user_id),
    }
    virtual_roots: list[tuple[str, str]] = []
    for section, root in roots.items():
        try:
            host_root = Path(root).resolve()
        except OSError:
            continue
        virtual_roots.append((host_root.as_posix(), f"/mnt/user-data/{section}"))
    virtual_roots.sort(key=lambda item: len(item[0]), reverse=True)
    return virtual_roots


def _sanitize_debug_export_string(value: str, virtual_path_roots: list[tuple[str, str]] | None) -> str:
    if not virtual_path_roots:
        return value
    sanitized = value
    for host_root, virtual_root in virtual_path_roots:
        sanitized = sanitized.replace(host_root, virtual_root)
    return sanitized


def _sanitize_encoded_debug_export_value(
    value: Any,
    *,
    virtual_path_roots: list[tuple[str, str]] | None = None,
) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _HIDDEN_CHAIN_OF_THOUGHT_KEYS:
                sanitized[key] = _hidden_chain_of_thought_redaction()
            else:
                sanitized[key] = _sanitize_encoded_debug_export_value(
                    item,
                    virtual_path_roots=virtual_path_roots,
                )
        return sanitized
    if isinstance(value, list):
        return [
            _sanitize_encoded_debug_export_value(
                item,
                virtual_path_roots=virtual_path_roots,
            )
            for item in value
        ]
    if isinstance(value, str):
        return _sanitize_debug_export_string(value, virtual_path_roots)
    return value


def _sanitize_debug_export_value(
    value: Any,
    *,
    virtual_path_roots: list[tuple[str, str]] | None = None,
) -> Any:
    """Return a JSON-safe debug value without raw hidden chain-of-thought."""
    return _sanitize_encoded_debug_export_value(
        jsonable_encoder(value),
        virtual_path_roots=virtual_path_roots,
    )


def _redaction_report_path(parent: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    key_text = str(key)
    if key_text.isidentifier():
        return f"{parent}.{key_text}"
    return f"{parent}[{json.dumps(key_text)}]"


def _collect_hidden_chain_of_thought_redactions(
    value: Any,
    *,
    path: str = "$",
    path_limit: int = 200,
) -> tuple[int, list[str], bool]:
    count = 0
    paths: list[str] = []
    truncated = False

    def visit(item: Any, item_path: str) -> None:
        nonlocal count, truncated
        if isinstance(item, dict) and item.get("redacted") is True and item.get("reason") == "hidden_chain_of_thought":
            count += 1
            if len(paths) < path_limit:
                paths.append(item_path)
            else:
                truncated = True
            return

        if isinstance(item, dict):
            for key, child in item.items():
                visit(child, _redaction_report_path(item_path, key))
            return

        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, _redaction_report_path(item_path, index))

    visit(value, path)
    return count, paths, truncated


def _build_redaction_report(payload: dict[str, Any]) -> dict[str, Any]:
    count, paths, truncated = _collect_hidden_chain_of_thought_redactions(payload)
    return {
        "hidden_chain_of_thought": {
            "count": count,
            "paths": paths,
            "paths_truncated": truncated,
            "policy": "raw_hidden_chain_of_thought_not_exported",
        }
    }


def _parse_event_types(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    event_types = [item.strip() for item in raw.split(",") if item.strip()]
    return event_types or None


def _sha256_file(path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_png_dimensions(path) -> dict[str, int] | None:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) >= 24 and header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
        width, height = struct.unpack(">II", header[16:24])
        return {"width": int(width), "height": int(height)}
    return None


def _read_gif_dimensions(path) -> dict[str, int] | None:
    with path.open("rb") as handle:
        header = handle.read(10)
    if len(header) >= 10 and header[:6] in {b"GIF87a", b"GIF89a"}:
        width, height = struct.unpack("<HH", header[6:10])
        return {"width": int(width), "height": int(height)}
    return None


def _read_jpeg_dimensions(path) -> dict[str, int] | None:
    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            return None
        while True:
            marker_prefix = handle.read(1)
            if not marker_prefix:
                return None
            if marker_prefix != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if marker in {b"\xd8", b"\xd9"}:
                continue
            size_bytes = handle.read(2)
            if len(size_bytes) != 2:
                return None
            segment_size = struct.unpack(">H", size_bytes)[0]
            if segment_size < 2:
                return None
            if marker and marker[0] in range(0xC0, 0xD0) and marker[0] not in {0xC4, 0xC8, 0xCC}:
                data = handle.read(5)
                if len(data) != 5:
                    return None
                height, width = struct.unpack(">HH", data[1:5])
                return {"width": int(width), "height": int(height)}
            handle.seek(segment_size - 2, 1)


def _image_metadata(path, mime_type: str | None) -> dict[str, Any] | None:
    try:
        if mime_type == "image/png":
            return _read_png_dimensions(path)
        if mime_type == "image/gif":
            return _read_gif_dimensions(path)
        if mime_type == "image/jpeg":
            return _read_jpeg_dimensions(path)
    except OSError:
        return None
    return None


def _file_entry(
    *,
    thread_id: str,
    section: str,
    root,
    path,
    include_file_contents: bool,
    file_content_max_bytes: int,
) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    virtual_path = f"/mnt/user-data/{section}/{relative}"
    quoted_virtual_path = quote(virtual_path.lstrip("/"), safe="/")
    stat = path.stat()
    mime_type, _ = mimetypes.guess_type(path.name)
    entry: dict[str, Any] = {
        "section": section,
        "relative_path": relative,
        "virtual_path": virtual_path,
        "download_url": f"/api/threads/{quote(thread_id, safe='')}/artifacts/{quoted_virtual_path}",
        "size_bytes": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": _sha256_file(path),
        "mime_type": mime_type or "application/octet-stream",
    }
    image = _image_metadata(path, mime_type)
    if image is not None:
        entry["image"] = image

    if include_file_contents:
        if stat.st_size <= file_content_max_bytes:
            entry["content_encoding"] = "base64"
            entry["content_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
        else:
            entry["content_omitted_reason"] = "file_too_large"
            entry["content_max_bytes"] = file_content_max_bytes
    return entry


def _collect_thread_files(
    *,
    thread_id: str,
    user_id: str | None,
    include_file_contents: bool,
    file_content_max_bytes: int,
    file_manifest_max_files: int,
) -> dict[str, Any]:
    paths = get_paths()
    roots = {
        "workspace": paths.sandbox_work_dir(thread_id, user_id=user_id),
        "uploads": paths.sandbox_uploads_dir(thread_id, user_id=user_id),
        "outputs": paths.sandbox_outputs_dir(thread_id, user_id=user_id),
    }
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in roots}
    total_files = 0
    total_bytes = 0
    truncated = False

    for section, root in roots.items():
        if not root.exists():
            continue
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            if total_files >= file_manifest_max_files:
                truncated = True
                break
            try:
                resolved_root = root.resolve()
                resolved_file = file_path.resolve()
                resolved_file.relative_to(resolved_root)
                entry = _file_entry(
                    thread_id=thread_id,
                    section=section,
                    root=resolved_root,
                    path=resolved_file,
                    include_file_contents=include_file_contents,
                    file_content_max_bytes=file_content_max_bytes,
                )
            except (OSError, ValueError):
                continue
            sections[section].append(entry)
            total_files += 1
            total_bytes += int(entry["size_bytes"])
        if truncated:
            break

    return {
        "included": True,
        "include_file_contents": include_file_contents,
        "file_content_max_bytes": file_content_max_bytes,
        "file_manifest_max_files": file_manifest_max_files,
        "truncated": truncated,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "sections": sections,
    }


def _iter_thread_file_paths(*, thread_id: str, user_id: str | None, file_manifest_max_files: int):
    paths = get_paths()
    roots = {
        "workspace": paths.sandbox_work_dir(thread_id, user_id=user_id),
        "uploads": paths.sandbox_uploads_dir(thread_id, user_id=user_id),
        "outputs": paths.sandbox_outputs_dir(thread_id, user_id=user_id),
    }
    yielded = 0
    for section, root in roots.items():
        if not root.exists():
            continue
        resolved_root = root.resolve()
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            if yielded >= file_manifest_max_files:
                return
            try:
                resolved_file = file_path.resolve()
                relative = resolved_file.relative_to(resolved_root).as_posix()
            except (OSError, ValueError):
                continue
            yielded += 1
            yield section, relative, resolved_file


async def _build_thread_debug_export(
    *,
    thread_id: str,
    request: Request,
    run_limit: int,
    event_limit_per_run: int,
    event_types: str | None,
    include_files: bool,
    include_file_contents: bool,
    file_content_max_bytes: int,
    file_manifest_max_files: int,
) -> dict:
    run_store = get_run_store(request)
    event_store = get_run_event_store(request)
    user_id = await get_current_user(request)
    parsed_event_types = _parse_event_types(event_types)
    virtual_path_roots = _thread_virtual_path_roots(thread_id, user_id)

    runs = await run_store.list_by_thread(thread_id, user_id=user_id, limit=run_limit)
    sorted_runs = sorted(runs, key=lambda row: str(row.get("created_at") or ""))
    exported_runs = []
    for run in sorted_runs:
        run_id = str(run["run_id"])
        events = await event_store.list_events(
            thread_id,
            run_id,
            event_types=parsed_event_types,
            limit=event_limit_per_run,
        )
        exported_runs.append(
            {
                "run": _sanitize_debug_export_value(run, virtual_path_roots=virtual_path_roots),
                "event_count": len(events),
                "events": _sanitize_debug_export_value(events, virtual_path_roots=virtual_path_roots),
            }
        )

    token_usage = await run_store.aggregate_tokens_by_thread(thread_id)
    payload = {
        "schema_version": 1,
        "thread_id": thread_id,
        "export_policy": {
            "hidden_chain_of_thought": "redacted",
            "included": [
                "messages",
                "tool_calls",
                "tool_results",
                "run_lifecycle_events",
                "middleware_events",
                "token_usage",
                "thread_files",
            ],
        },
        "filters": {
            "run_limit": run_limit,
            "event_limit_per_run": event_limit_per_run,
            "event_types": parsed_event_types,
            "include_files": include_files,
            "include_file_contents": include_file_contents,
            "file_content_max_bytes": file_content_max_bytes,
            "file_manifest_max_files": file_manifest_max_files,
        },
        "token_usage": _sanitize_debug_export_value(token_usage, virtual_path_roots=virtual_path_roots),
        "files": _collect_thread_files(
            thread_id=thread_id,
            user_id=user_id,
            include_file_contents=include_file_contents,
            file_content_max_bytes=file_content_max_bytes,
            file_manifest_max_files=file_manifest_max_files,
        )
        if include_files
        else {"included": False},
        "runs": exported_runs,
    }
    payload["redaction_report"] = _build_redaction_report(payload)
    return payload


def _build_debug_export_archive(*, thread_id: str, user_id: str | None, payload: dict, file_manifest_max_files: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("trace.json", json.dumps(payload, ensure_ascii=False, indent=2))
        if payload.get("files", {}).get("included"):
            for section, relative, file_path in _iter_thread_file_paths(
                thread_id=thread_id,
                user_id=user_id,
                file_manifest_max_files=file_manifest_max_files,
            ):
                archive.write(file_path, f"files/{section}/{relative}")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{thread_id}/runs", response_model=RunResponse)
@require_permission("runs", "create", owner_check=True, require_existing=True)
async def create_run(thread_id: str, body: RunCreateRequest, request: Request) -> RunResponse:
    """Create a background run (returns immediately)."""
    record = await start_run(body, thread_id, request)
    return _record_to_response(record)


@router.post("/{thread_id}/runs/stream")
@require_permission("runs", "create", owner_check=True, require_existing=True)
async def stream_run(thread_id: str, body: RunCreateRequest, request: Request) -> StreamingResponse:
    """Create a run and stream events via SSE.

    The response includes a ``Content-Location`` header with the run's
    resource URL, matching the LangGraph Platform protocol.  The
    ``useStream`` React hook uses this to extract run metadata.
    """
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    record = await start_run(body, thread_id, request)

    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            # LangGraph Platform includes run metadata in this header.
            # The SDK uses a greedy regex to extract the run id from this path,
            # so it must point at the canonical run resource without extra suffixes.
            "Content-Location": f"/api/threads/{thread_id}/runs/{record.run_id}",
        },
    )


@router.post("/{thread_id}/runs/wait", response_model=dict)
@require_permission("runs", "create", owner_check=True, require_existing=True)
async def wait_run(thread_id: str, body: RunCreateRequest, request: Request) -> dict:
    """Create a run and block until it completes, returning the final state."""
    record = await start_run(body, thread_id, request)

    if record.task is not None:
        try:
            await record.task
        except asyncio.CancelledError:
            pass

    checkpointer = get_checkpointer(request)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        checkpoint_tuple = await checkpointer.aget_tuple(config)
        if checkpoint_tuple is not None:
            checkpoint = getattr(checkpoint_tuple, "checkpoint", {}) or {}
            channel_values = checkpoint.get("channel_values", {})
            return serialize_channel_values(channel_values)
    except Exception:
        logger.exception("Failed to fetch final state for run %s", record.run_id)

    return {"status": record.status.value, "error": record.error}


@router.get("/{thread_id}/runs", response_model=list[RunResponse])
@require_permission("runs", "read", owner_check=True)
async def list_runs(thread_id: str, request: Request) -> list[RunResponse]:
    """List all runs for a thread."""
    run_mgr = get_run_manager(request)
    records = await run_mgr.list_by_thread(thread_id)
    return [_record_to_response(r) for r in records]


@router.get("/{thread_id}/runs/{run_id}", response_model=RunResponse)
@require_permission("runs", "read", owner_check=True)
async def get_run(thread_id: str, run_id: str, request: Request) -> RunResponse:
    """Get details of a specific run."""
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return _record_to_response(record)


@router.post("/{thread_id}/runs/{run_id}/cancel")
@require_permission("runs", "cancel", owner_check=True, require_existing=True)
async def cancel_run(
    thread_id: str,
    run_id: str,
    request: Request,
    wait: bool = Query(default=False, description="Block until run completes after cancel"),
    action: Literal["interrupt", "rollback"] = Query(default="interrupt", description="Cancel action"),
) -> Response:
    """Cancel a running or pending run.

    - action=interrupt: Stop execution, keep current checkpoint (can be resumed)
    - action=rollback: Stop execution, revert to pre-run checkpoint state
    - wait=true: Block until the run fully stops, return 204
    - wait=false: Return immediately with 202
    """
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    cancelled = await run_mgr.cancel(run_id, action=action)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} is not cancellable (status: {record.status.value})",
        )

    if wait and record.task is not None:
        try:
            await record.task
        except asyncio.CancelledError:
            pass
        return Response(status_code=204)

    return Response(status_code=202)


@router.get("/{thread_id}/runs/{run_id}/join")
@require_permission("runs", "read", owner_check=True)
async def join_run(thread_id: str, run_id: str, request: Request) -> StreamingResponse:
    """Join an existing run's SSE stream."""
    bridge = get_stream_bridge(request)
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.api_route("/{thread_id}/runs/{run_id}/stream", methods=["GET", "POST"], response_model=None)
@require_permission("runs", "read", owner_check=True)
async def stream_existing_run(
    thread_id: str,
    run_id: str,
    request: Request,
    action: Literal["interrupt", "rollback"] | None = Query(default=None, description="Cancel action"),
    wait: int = Query(default=0, description="Block until cancelled (1) or return immediately (0)"),
):
    """Join an existing run's SSE stream (GET), or cancel-then-stream (POST).

    The LangGraph SDK's ``joinStream`` and ``useStream`` stop button both use
    ``POST`` to this endpoint.  When ``action=interrupt`` or ``action=rollback``
    is present the run is cancelled first; the response then streams any
    remaining buffered events so the client observes a clean shutdown.
    """
    run_mgr = get_run_manager(request)
    record = run_mgr.get(run_id)
    if record is None or record.thread_id != thread_id:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Cancel if an action was requested (stop-button / interrupt flow)
    if action is not None:
        cancelled = await run_mgr.cancel(run_id, action=action)
        if cancelled and wait and record.task is not None:
            try:
                await record.task
            except (asyncio.CancelledError, Exception):
                pass
            return Response(status_code=204)

    bridge = get_stream_bridge(request)
    return StreamingResponse(
        sse_consumer(bridge, record, request, run_mgr),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Messages / Events / Token usage endpoints
# ---------------------------------------------------------------------------


@router.get("/{thread_id}/messages")
@require_permission("runs", "read", owner_check=True)
async def list_thread_messages(
    thread_id: str,
    request: Request,
    limit: int = Query(default=50, le=200),
    before_seq: int | None = Query(default=None),
    after_seq: int | None = Query(default=None),
) -> list[dict]:
    """Return displayable messages for a thread (across all runs), with feedback attached."""
    event_store = get_run_event_store(request)
    messages = await event_store.list_messages(thread_id, limit=limit, before_seq=before_seq, after_seq=after_seq)

    # Attach feedback to the last AI message of each run
    feedback_repo = get_feedback_repo(request)
    user_id = await get_current_user(request)
    feedback_map = await feedback_repo.list_by_thread_grouped(thread_id, user_id=user_id)

    # Find the last ai_message per run_id
    last_ai_per_run: dict[str, int] = {}  # run_id -> index in messages list
    for i, msg in enumerate(messages):
        if msg.get("event_type") == "ai_message":
            last_ai_per_run[msg["run_id"]] = i

    # Attach feedback field
    last_ai_indices = set(last_ai_per_run.values())
    for i, msg in enumerate(messages):
        if i in last_ai_indices:
            run_id = msg["run_id"]
            fb = feedback_map.get(run_id)
            msg["feedback"] = (
                {
                    "feedback_id": fb["feedback_id"],
                    "rating": fb["rating"],
                    "comment": fb.get("comment"),
                }
                if fb
                else None
            )
        else:
            msg["feedback"] = None

    return messages


@router.get("/{thread_id}/runs/{run_id}/messages")
@require_permission("runs", "read", owner_check=True)
async def list_run_messages(
    thread_id: str,
    run_id: str,
    request: Request,
    limit: int = Query(default=50, le=200, ge=1),
    before_seq: int | None = Query(default=None),
    after_seq: int | None = Query(default=None),
) -> dict:
    """Return paginated messages for a specific run.

    Response: { data: [...], has_more: bool }
    """
    event_store = get_run_event_store(request)
    rows = await event_store.list_messages_by_run(
        thread_id,
        run_id,
        limit=limit + 1,
        before_seq=before_seq,
        after_seq=after_seq,
    )
    has_more = len(rows) > limit
    data = rows[:limit] if has_more else rows
    return {"data": data, "has_more": has_more}


@router.get("/{thread_id}/runs/{run_id}/events")
@require_permission("runs", "read", owner_check=True)
async def list_run_events(
    thread_id: str,
    run_id: str,
    request: Request,
    event_types: str | None = Query(default=None),
    limit: int = Query(default=500, le=2000),
) -> list[dict]:
    """Return the full event stream for a run (debug/audit)."""
    event_store = get_run_event_store(request)
    types = event_types.split(",") if event_types else None
    return await event_store.list_events(thread_id, run_id, event_types=types, limit=limit)


@router.get("/{thread_id}/debug-export")
@require_permission("runs", "read", owner_check=True)
async def export_thread_debug_trace(
    thread_id: str,
    request: Request,
    run_limit: int = Query(default=100, le=500, ge=1),
    event_limit_per_run: int = Query(default=2000, le=10000, ge=1),
    event_types: str | None = Query(default=None),
    include_files: bool = Query(default=True),
    include_file_contents: bool = Query(default=False),
    file_content_max_bytes: int = Query(default=262144, le=2097152, ge=0),
    file_manifest_max_files: int = Query(default=500, le=5000, ge=1),
) -> dict:
    """Export the persisted debug/audit trace for a thread.

    This endpoint exports stored messages, tool calls/results, lifecycle
    events, middleware events, and token aggregates. It deliberately redacts
    raw hidden chain-of-thought fields if a provider or middleware persisted
    them in message metadata.
    """
    return await _build_thread_debug_export(
        thread_id=thread_id,
        request=request,
        run_limit=run_limit,
        event_limit_per_run=event_limit_per_run,
        event_types=event_types,
        include_files=include_files,
        include_file_contents=include_file_contents,
        file_content_max_bytes=file_content_max_bytes,
        file_manifest_max_files=file_manifest_max_files,
    )


@router.get("/{thread_id}/debug-export/archive")
@require_permission("runs", "read", owner_check=True)
async def export_thread_debug_archive(
    thread_id: str,
    request: Request,
    run_limit: int = Query(default=100, le=500, ge=1),
    event_limit_per_run: int = Query(default=2000, le=10000, ge=1),
    event_types: str | None = Query(default=None),
    include_files: bool = Query(default=True),
    file_manifest_max_files: int = Query(default=500, le=5000, ge=1),
) -> Response:
    """Export trace.json plus thread files as a ZIP archive."""
    payload = await _build_thread_debug_export(
        thread_id=thread_id,
        request=request,
        run_limit=run_limit,
        event_limit_per_run=event_limit_per_run,
        event_types=event_types,
        include_files=include_files,
        include_file_contents=False,
        file_content_max_bytes=0,
        file_manifest_max_files=file_manifest_max_files,
    )
    user_id = await get_current_user(request)
    content = _build_debug_export_archive(
        thread_id=thread_id,
        user_id=user_id,
        payload=payload,
        file_manifest_max_files=file_manifest_max_files,
    )
    filename = f"deerflow-debug-export-{thread_id}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{thread_id}/token-usage")
@require_permission("threads", "read", owner_check=True)
async def thread_token_usage(thread_id: str, request: Request) -> dict:
    """Thread-level token usage aggregation."""
    run_store = get_run_store(request)
    agg = await run_store.aggregate_tokens_by_thread(thread_id)
    return {"thread_id": thread_id, **agg}
