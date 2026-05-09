"""Tests for GET /api/threads/{thread_id}/debug-export."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.gateway.routers import thread_runs


def _make_app(run_store=None, event_store=None):
    app = make_authed_test_app()
    app.include_router(thread_runs.router)
    if run_store is not None:
        app.state.run_store = run_store
    if event_store is not None:
        app.state.run_event_store = event_store
    return app


def test_debug_export_returns_runs_and_events():
    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(
        return_value=[
            {
                "run_id": "run-1",
                "thread_id": "thread-1",
                "status": "success",
                "created_at": "2026-05-09T00:00:00Z",
            }
        ]
    )
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value={"total_tokens": 12})

    event_store = MagicMock()
    event_store.list_events = AsyncMock(
        return_value=[
            {
                "seq": 1,
                "thread_id": "thread-1",
                "run_id": "run-1",
                "event_type": "llm.tool.result",
                "category": "message",
                "content": {"type": "tool", "name": "read_file", "content": "ok"},
                "metadata": {},
            }
        ]
    )

    app = _make_app(run_store=run_store, event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/debug-export")

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "thread-1"
    assert body["schema_version"] == 1
    assert body["runs"][0]["run"]["run_id"] == "run-1"
    assert body["runs"][0]["events"][0]["event_type"] == "llm.tool.result"
    assert body["token_usage"]["total_tokens"] == 12
    run_store.list_by_thread.assert_awaited_once()
    event_store.list_events.assert_awaited_once_with("thread-1", "run-1", event_types=None, limit=2000)


def test_debug_export_redacts_hidden_chain_of_thought_fields():
    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(return_value=[{"run_id": "run-1", "thread_id": "thread-1", "status": "success"}])
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value={})

    event_store = MagicMock()
    event_store.list_events = AsyncMock(
        return_value=[
            {
                "seq": 1,
                "thread_id": "thread-1",
                "run_id": "run-1",
                "event_type": "llm.ai.response",
                "category": "message",
                "content": {
                    "content": "visible answer",
                    "additional_kwargs": {
                        "reasoning_content": "hidden private reasoning",
                        "thinking": "hidden provider thinking",
                        "reasoning_summary": "safe short summary",
                    },
                },
                "metadata": {"reasoning_content": "hidden metadata reasoning"},
            }
        ]
    )

    app = _make_app(run_store=run_store, event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/debug-export")

    assert response.status_code == 200
    raw = response.text
    assert "hidden private reasoning" not in raw
    assert "hidden provider thinking" not in raw
    assert "hidden metadata reasoning" not in raw
    assert "safe short summary" in raw
    event = response.json()["runs"][0]["events"][0]
    assert event["content"]["additional_kwargs"]["reasoning_content"]["redacted"] is True
    assert event["content"]["additional_kwargs"]["thinking"]["reason"] == "hidden_chain_of_thought"
    assert event["metadata"]["reasoning_content"]["reason"] == "hidden_chain_of_thought"
    report = response.json()["redaction_report"]["hidden_chain_of_thought"]
    assert report["count"] == 3
    assert any("reasoning_content" in path for path in report["paths"])
    assert any("thinking" in path for path in report["paths"])
    assert report["policy"] == "raw_hidden_chain_of_thought_not_exported"


def test_debug_export_filters_event_types():
    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(return_value=[{"run_id": "run-1", "thread_id": "thread-1", "status": "success"}])
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value={})

    event_store = MagicMock()
    event_store.list_events = AsyncMock(return_value=[])

    app = _make_app(run_store=run_store, event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/debug-export?event_types=llm.ai.response,llm.tool.result&event_limit_per_run=50")

    assert response.status_code == 200
    event_store.list_events.assert_awaited_once_with(
        "thread-1",
        "run-1",
        event_types=["llm.ai.response", "llm.tool.result"],
        limit=50,
    )


def test_debug_export_includes_thread_file_manifest(tmp_path, monkeypatch):
    class FakePaths:
        def sandbox_work_dir(self, thread_id, *, user_id=None):
            return tmp_path / "workspace"

        def sandbox_uploads_dir(self, thread_id, *, user_id=None):
            return tmp_path / "uploads"

        def sandbox_outputs_dir(self, thread_id, *, user_id=None):
            return tmp_path / "outputs"

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    # Minimal 1x1 PNG header/chunks; enough for image dimension parsing.
    (uploads / "plan.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
    monkeypatch.setattr(thread_runs, "get_paths", lambda: FakePaths())

    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(return_value=[])
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value={})
    event_store = MagicMock()

    app = _make_app(run_store=run_store, event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/debug-export")

    assert response.status_code == 200
    files = response.json()["files"]
    assert files["total_files"] == 1
    file_entry = files["sections"]["uploads"][0]
    assert file_entry["virtual_path"] == "/mnt/user-data/uploads/plan.png"
    assert file_entry["download_url"] == "/api/threads/thread-1/artifacts/mnt/user-data/uploads/plan.png"
    assert file_entry["mime_type"] == "image/png"
    assert file_entry["image"]["width"] == 1
    assert file_entry["image"]["height"] == 1
    assert "host_path" not in file_entry


def test_debug_export_can_inline_small_file_contents(tmp_path, monkeypatch):
    class FakePaths:
        def sandbox_work_dir(self, thread_id, *, user_id=None):
            return tmp_path / "workspace"

        def sandbox_uploads_dir(self, thread_id, *, user_id=None):
            return tmp_path / "uploads"

        def sandbox_outputs_dir(self, thread_id, *, user_id=None):
            return tmp_path / "outputs"

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "notes.txt").write_text("hello export", encoding="utf-8")
    monkeypatch.setattr(thread_runs, "get_paths", lambda: FakePaths())

    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(return_value=[])
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value={})
    event_store = MagicMock()

    app = _make_app(run_store=run_store, event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/debug-export?include_file_contents=true")

    assert response.status_code == 200
    file_entry = response.json()["files"]["sections"]["outputs"][0]
    assert file_entry["content_encoding"] == "base64"
    assert base64.b64decode(file_entry["content_base64"]).decode("utf-8") == "hello export"


def test_debug_export_virtualizes_thread_data_host_paths(tmp_path, monkeypatch):
    class FakePaths:
        def sandbox_work_dir(self, thread_id, *, user_id=None):
            return tmp_path / "workspace"

        def sandbox_uploads_dir(self, thread_id, *, user_id=None):
            return tmp_path / "uploads"

        def sandbox_outputs_dir(self, thread_id, *, user_id=None):
            return tmp_path / "outputs"

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "plan.png").write_bytes(b"not a real image")
    monkeypatch.setattr(thread_runs, "get_paths", lambda: FakePaths())

    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(return_value=[{"run_id": "run-1", "thread_id": "thread-1", "status": "success"}])
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value={})

    event_store = MagicMock()
    event_store.list_events = AsyncMock(
        return_value=[
            {
                "seq": 1,
                "thread_id": "thread-1",
                "run_id": "run-1",
                "event_type": "thread_context",
                "category": "trace",
                "content": {
                    "thread_data": {
                        "uploads_path": str(uploads.resolve()),
                        "image_path": str((uploads / "plan.png").resolve()),
                    }
                },
                "metadata": {},
            }
        ]
    )

    app = _make_app(run_store=run_store, event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/debug-export?include_files=false")

    assert response.status_code == 200
    assert str(tmp_path) not in response.text
    thread_data = response.json()["runs"][0]["events"][0]["content"]["thread_data"]
    assert thread_data["uploads_path"] == "/mnt/user-data/uploads"
    assert thread_data["image_path"] == "/mnt/user-data/uploads/plan.png"


def test_debug_export_archive_contains_trace_and_files(tmp_path, monkeypatch):
    class FakePaths:
        def sandbox_work_dir(self, thread_id, *, user_id=None):
            return tmp_path / "workspace"

        def sandbox_uploads_dir(self, thread_id, *, user_id=None):
            return tmp_path / "uploads"

        def sandbox_outputs_dir(self, thread_id, *, user_id=None):
            return tmp_path / "outputs"

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    png_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    (uploads / "plan.png").write_bytes(png_bytes)
    monkeypatch.setattr(thread_runs, "get_paths", lambda: FakePaths())

    run_store = MagicMock()
    run_store.list_by_thread = AsyncMock(return_value=[])
    run_store.aggregate_tokens_by_thread = AsyncMock(return_value={})
    event_store = MagicMock()

    app = _make_app(run_store=run_store, event_store=event_store)
    with TestClient(app) as client:
        response = client.get("/api/threads/thread-1/debug-export/archive")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "trace.json" in names
        assert "files/uploads/plan.png" in names
        assert archive.read("files/uploads/plan.png") == png_bytes
        trace = json.loads(archive.read("trace.json").decode("utf-8"))
    assert trace["files"]["total_files"] == 1
    assert "host_path" not in json.dumps(trace)


def test_debug_export_redacts_thinking_after_json_encoding():
    class ProviderBlock(BaseModel):
        type: str
        thinking: str

    class ProviderMessage(BaseModel):
        content: list[ProviderBlock]

    sanitized = thread_runs._sanitize_debug_export_value(
        {
            "content": {
                "messages": [
                    ProviderMessage(
                        content=[
                            ProviderBlock(
                                type="thinking",
                                thinking="hidden provider object thinking",
                            )
                        ]
                    )
                ]
            }
        }
    )

    assert "hidden provider object thinking" not in str(sanitized)
    assert sanitized["content"]["messages"][0]["content"][0]["thinking"]["reason"] == "hidden_chain_of_thought"
    report = thread_runs._build_redaction_report(sanitized)
    assert report["hidden_chain_of_thought"]["count"] == 1
    assert report["hidden_chain_of_thought"]["paths"] == ["$.content.messages[0].content[0].thinking"]
