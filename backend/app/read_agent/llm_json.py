from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import httpx

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


class LlmNotConfigured(RuntimeError):
    pass


def llm_is_configured() -> bool:
    return bool(os.environ.get("READ_AGENT_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _base_url() -> str:
    raw = os.environ.get("READ_AGENT_LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    return raw.rstrip("/")


def _api_key() -> str:
    key = os.environ.get("READ_AGENT_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise LlmNotConfigured("READ_AGENT_LLM_API_KEY or OPENAI_API_KEY is required for real read-agent recognition")
    return key


def _model() -> str:
    return os.environ.get("READ_AGENT_LLM_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-4.1"


def _image_limit_bytes() -> int:
    return int(os.environ.get("READ_AGENT_MAX_IMAGE_BYTES", str(8 * 1024 * 1024)))


def _data_uri(path: Path) -> str:
    size = path.stat().st_size
    if size > _image_limit_bytes():
        raise ValueError(f"Image exceeds READ_AGENT_MAX_IMAGE_BYTES: {path} ({size} bytes)")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if match := _JSON_BLOCK_RE.search(text):
        text = match.group(1).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("LLM response did not contain a JSON object")


def chat_json(
    *,
    system_prompt: str,
    user_prompt: str,
    image_paths: list[Path] | None = None,
    response_schema_hint: dict[str, Any] | None = None,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Call an OpenAI-compatible vision model and require a JSON object response.

    If no model key is configured, it raises LlmNotConfigured so the pipeline
    records a real blocker instead of fabricating recognition results.
    """
    key = _api_key()
    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image_path in image_paths or []:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(image_path)}})
    if response_schema_hint:
        content.insert(
            0,
            {
                "type": "text",
                "text": "Return exactly one JSON object. Schema hint:\n" + json.dumps(response_schema_hint, ensure_ascii=False),
            },
        )

    payload = {
        "model": _model(),
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    }
    # Many OpenAI-compatible endpoints support this. If one does not, it will
    # ignore the field or return a clear API error.
    payload["response_format"] = {"type": "json_object"}

    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(
            f"{_base_url()}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        decoded = response.json()
    content_text = decoded["choices"][0]["message"]["content"]
    return extract_json_object(content_text)
