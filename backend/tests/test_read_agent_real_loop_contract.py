from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.gateway import deps
from app.gateway.app import create_app
from app.gateway.auth.config import AuthConfig, set_auth_config
from deerflow.persistence.engine import close_engine, init_engine


@pytest.fixture(autouse=True)
def _auth_engine(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/auth.db"
    asyncio.run(init_engine("sqlite", url=url, sqlite_dir=str(tmp_path)))
    deps._cached_local_provider = None
    deps._cached_repo = None
    try:
        yield
    finally:
        deps._cached_local_provider = None
        deps._cached_repo = None
        asyncio.run(close_engine())


def _login_test_account(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"email": "test@qq.com", "password": "test@qq.com"},
    )
    login = client.post(
        "/api/v1/auth/login/local",
        data={"username": "test@qq.com", "password": "test@qq.com"},
    )
    assert login.status_code == 200
    csrf_token = client.cookies.get("csrf_token") or "read-agent-contract-test"
    client.cookies.set("csrf_token", csrf_token)
    return {"X-CSRF-Token": csrf_token}


def test_read_agent_upload_run_edit_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("READ_AGENT_DATA_ROOT", str(tmp_path / "read-agent-data"))
    monkeypatch.delenv("READ_AGENT_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    set_auth_config(AuthConfig(jwt_secret="read-agent-contract-test-secret-min32"))
    client = TestClient(create_app())
    csrf_headers = _login_test_account(client)

    project = client.post(
        "/api/read-agent/projects",
        json={"name": "loop-test", "building_id": "B01", "building_name": "主楼"},
        headers=csrf_headers,
    ).json()["project"]

    image_path = tmp_path / "sheet.png"
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.line((100, 100, 700, 100), fill="black", width=3)
    draw.text((120, 80), "KL1(1) 300x600", fill="black")
    image.save(image_path)

    with image_path.open("rb") as handle:
        uploaded = client.post(
            f"/api/read-agent/projects/{project['project_id']}/blueprints",
            data={"building_id": "B01", "building_name": "主楼", "floor_id": "F01", "floor_name": "一层", "floor_index": "1", "drawing_type": "structural_plan"},
            files={"files": ("sheet.png", handle, "image/png")},
            headers=csrf_headers,
        )
    assert uploaded.status_code == 200
    assert uploaded.json()["blueprints"][0]["status"] == "uploaded"

    run = client.post(
        "/api/read-agent/runs",
        json={"project_id": project["project_id"], "floor_ids": ["F01"], "target_stages": ["stage1", "stage2"]},
        headers=csrf_headers,
    )
    assert run.status_code == 200
    # The actual background task runs under FastAPI BackgroundTasks. In tests this
    # verifies at least that no PL-S-001 demo gate is required and run creation is dynamic.
    view = client.get(f"/api/read-agent/projects/{project['project_id']}/floors/F01/view-model")
    assert view.status_code == 200
