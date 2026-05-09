# Agent Debug Export

This document is the authoritative project note for exporting DeerFlow agent execution traces during development.

## Purpose

Development and evaluation workflows need a reproducible record of how an agent responded inside a conversation. The debug export API provides a thread-level bundle containing persisted messages, tool calls, tool results, run lifecycle events, middleware events, and token usage.

## Acceptance Scope

This feature is accepted as a safe development export, not as a raw hidden chain-of-thought dump.

Included:

- persisted conversation trace and run events;
- tool calls and tool results when stored in the run event stream;
- token usage aggregates;
- thread file manifests for workspace/uploads/outputs;
- original thread files in the ZIP archive;
- UI downloads for debug JSON and debug ZIP;
- hidden chain-of-thought redaction markers, paths, and counts.

Not included:

- raw hidden model deliberation;
- provider-private reasoning text;
- reconstructed chain-of-thought from hidden fields.

The durable research signal is the visible trace plus `redaction_report.hidden_chain_of_thought`: it proves where hidden reasoning-like data was blocked without exporting that private text.

## API

```http
GET /api/threads/{thread_id}/debug-export
```

For a complete development bundle:

```http
GET /api/threads/{thread_id}/debug-export/archive
```

The archive endpoint returns `application/zip` with:

- `trace.json`: the same JSON debug export payload.
- `files/workspace/**`: agent workspace files.
- `files/uploads/**`: user-uploaded files, including images.
- `files/outputs/**`: agent-generated output artifacts.

The workspace export menu also exposes:

- `Export debug JSON`: downloads `/api/threads/{thread_id}/debug-export`.
- `Export debug ZIP`: downloads `/api/threads/{thread_id}/debug-export/archive`.

The debug export menu remains available for concrete thread IDs even if the visible message list is empty. This matters during development because persisted run events, uploaded files, and generated artifacts can exist before the React message list has rendered or rehydrated.

Query parameters:

- `run_limit`: maximum runs to include. Default `100`, maximum `500`.
- `event_limit_per_run`: maximum events per run. Default `2000`, maximum `10000`.
- `event_types`: optional comma-separated event type filter, for example `llm.ai.response,llm.tool.result`.
- `include_files`: include the thread file manifest. Default `true`.
- `include_file_contents`: inline file bytes as base64 when files are within `file_content_max_bytes`. Default `false`.
- `file_content_max_bytes`: maximum per-file bytes to inline when `include_file_contents=true`. Default `262144`, maximum `2097152`.
- `file_manifest_max_files`: maximum file entries in the manifest. Default `500`, maximum `5000`.

The response shape:

```json
{
  "schema_version": 1,
  "thread_id": "thread-id",
  "export_policy": {
    "hidden_chain_of_thought": "redacted",
    "included": [
      "messages",
      "tool_calls",
      "tool_results",
      "run_lifecycle_events",
      "middleware_events",
      "token_usage",
      "thread_files"
    ]
  },
  "filters": {
    "run_limit": 100,
    "event_limit_per_run": 2000,
    "event_types": null,
    "include_files": true,
    "include_file_contents": false,
    "file_content_max_bytes": 262144,
    "file_manifest_max_files": 500
  },
  "token_usage": {},
  "files": {
    "included": true,
    "include_file_contents": false,
    "total_files": 0,
    "total_bytes": 0,
    "sections": {
      "workspace": [],
      "uploads": [],
      "outputs": []
    }
  },
  "runs": [
    {
      "run": {},
      "event_count": 0,
      "events": []
    }
  ],
  "redaction_report": {
    "hidden_chain_of_thought": {
      "count": 0,
      "paths": [],
      "paths_truncated": false,
      "policy": "raw_hidden_chain_of_thought_not_exported"
    }
  }
}
```

## Chain-of-Thought Boundary

Raw hidden chain-of-thought must not be exported. If provider output or metadata contains fields such as `reasoning_content`, `thinking`, `thinking_blocks`, `chain_of_thought`, `cot`, `thought`, or `thoughts`, the export replaces the field value with:

```json
{
  "redacted": true,
  "reason": "hidden_chain_of_thought"
}
```

Allowed reasoning-related data:

- visible final answers;
- tool call arguments;
- tool result content;
- visible short reasoning summaries if explicitly stored as summary fields;
- lifecycle, middleware, latency, and token metadata.
- thread file manifests for `/mnt/user-data/workspace`, `/mnt/user-data/uploads`, and `/mnt/user-data/outputs`.

Disallowed data:

- raw hidden model deliberation;
- provider-private reasoning content;
- reconstructed chain-of-thought from hidden fields.

The export also includes a redaction report:

```json
{
  "redaction_report": {
    "hidden_chain_of_thought": {
      "count": 3,
      "paths": [
        "$.runs[0].events[0].content.additional_kwargs.reasoning_content",
        "$.runs[0].events[0].content.additional_kwargs.thinking",
        "$.runs[0].events[0].metadata.reasoning_content"
      ],
      "paths_truncated": false,
      "policy": "raw_hidden_chain_of_thought_not_exported"
    }
  }
}
```

Use this report to audit where hidden reasoning was blocked. It is intentionally path-and-count only; it does not include the hidden text.

## File Export

The `files` section lists files involved in the thread data area:

- `workspace`: agent workspace files.
- `uploads`: user-uploaded files, including uploaded images.
- `outputs`: agent-generated artifacts.

Each file entry includes:

- `section`
- `relative_path`
- `virtual_path`
- `download_url`
- `size_bytes`
- `mtime`
- `sha256`
- `mime_type`
- `image.width` and `image.height` for supported image formats.

Host filesystem paths are intentionally not exported. Use `download_url` to fetch the file through the authenticated artifact endpoint.

Use `/debug-export/archive` when the development workflow needs the actual image files and generated artifacts in one bundle.

When `include_file_contents=true`, small files are included as base64:

```json
{
  "content_encoding": "base64",
  "content_base64": "..."
}
```

Large files are not inlined and receive:

```json
{
  "content_omitted_reason": "file_too_large"
}
```

## Development Test Account

For manual user-level development testing, use:

- email: `test@qq.com`
- password: `test@qq.com`

This account is for local development and Playwright-style UI simulation only. Do not encode it into production defaults.

## Verification

Backend behavior is covered by:

```bash
cd backend
uv run pytest tests/test_thread_debug_export.py -q
```

The tests verify:

- debug export returns runs and events;
- event type filtering is forwarded to the event store;
- hidden chain-of-thought fields are redacted and not present in the raw response body;
- hidden chain-of-thought redaction count and paths are reported without raw content;
- persisted thread-data host paths are virtualized to `/mnt/user-data/...`;
- thread workspace/uploads/outputs files are included in the file manifest;
- small file content can be inlined as base64 when explicitly requested;
- the ZIP archive contains `trace.json` and original thread files.

## 2026-05-09 Completion Audit

Objective translated to concrete deliverables:

- export development-grade conversation details for one DeerFlow thread;
- include message/run trace, tool calls/results, lifecycle or middleware events, and token usage when persisted;
- include involved image/file data through manifest metadata and an archive bundle;
- handle hidden chain-of-thought explicitly;
- record the behavior in authoritative Markdown;
- verify with repeatable backend tests and real browser-level user actions using the local development account.

Prompt-to-artifact checklist:

| Requirement | Artifact | Evidence |
| --- | --- | --- |
| Thread-level detailed export | `GET /api/threads/{thread_id}/debug-export` in `app/gateway/routers/thread_runs.py` | Returns `schema_version`, `thread_id`, `filters`, `token_usage`, `files`, and per-run `events`. |
| Tool/message/lifecycle trace export | `runs[].events[]` in the debug export response | Events are read through `RunEventStore.list_events()` with optional `event_types` and `event_limit_per_run`. |
| Image/file manifest | `files.sections.workspace`, `files.sections.uploads`, `files.sections.outputs` | File entries include virtual path, download URL, size, mtime, SHA-256, MIME type, and image dimensions for PNG/GIF/JPEG. |
| Original files for development reproduction | `GET /api/threads/{thread_id}/debug-export/archive` | ZIP contains `trace.json` plus `files/workspace/**`, `files/uploads/**`, and `files/outputs/**`. |
| Hidden chain-of-thought handling | `_sanitize_debug_export_value()` and `redaction_report.hidden_chain_of_thought` | Raw fields such as `reasoning_content`, `thinking`, `thinking_blocks`, `chain_of_thought`, `cot`, `thought`, and `thoughts` are replaced with redaction markers; report exposes count and paths only. |
| UI access to debug export | `frontend/src/components/workspace/export-trigger.tsx` | Workspace export menu downloads debug JSON and debug ZIP for concrete thread IDs, even when the visible React message list is empty. |
| Authoritative documentation | This file and `DEERFLOW_DOCS_INDEX.md` | Root index links to this document under core functionality. |
| Backend regression coverage | `tests/test_thread_debug_export.py` | Covers runs/events, event filtering, hidden-field redaction, redaction report, file manifest, inline base64 content, ZIP archive, and Pydantic/json encoding redaction. |
| Frontend regression coverage | `frontend/tests/unit/components/workspace/export-trigger.test.ts` | Covers that debug export remains available for concrete thread IDs even if visible messages are empty. |
| User-level browser coverage | Local Playwright run against `http://localhost:2026` | Used `test@qq.com` / `test@qq.com`; initialized/logged in, opened `/workspace/chats/new`, uploaded a 1x1 PNG, typed a prompt, clicked submit, fetched JSON export and ZIP archive, then downloaded debug JSON/ZIP through the UI menu. |

Verified command:

```bash
cd /mnt/e/deerflow-agent-lab/deer-flow/backend
uv run pytest tests/test_thread_debug_export.py tests/test_thread_run_messages_pagination.py tests/test_run_event_store.py -q
```

Latest result:

```text
59 passed in 1.41s
```

Frontend verification:

```bash
cd /mnt/e/deerflow-agent-lab/deer-flow/frontend
corepack pnpm test
corepack pnpm typecheck
```

Latest result:

```text
55 passed in 1.26s
tsc --noEmit passed
targeted export trigger test: 3 passed
```

Browser verification evidence:

- thread: `38471f81-c23e-40e6-98da-a8f17c4a40d7`
- `/debug-export`: HTTP `200`, `schema_version=1`, `runCount=1`, `eventCount=25`, `fileTotal=1`, `uploads=1`, `redactionCount=9`
- `/debug-export/archive`: HTTP `200`, `content-type=application/zip`, ZIP magic `50 4b 03 04`
- uploaded image manifest: `image/png`, `1x1`, `70` bytes, virtual path `/mnt/user-data/uploads/debug-export-audit.png`
- raw fixture leak check: false
- host path leak check: false
- redaction marker check: `redactionMarkerCount=9`, `redactionReportPathMismatch=false`
- UI menu downloads: `debug-export-ui.json` and `debug-export-ui.zip`; downloaded JSON has `schema_version=1`, `redactionCount=9`, `redactionMarkerCount=9`, `hostPathLeak=false`; downloaded ZIP magic is `50 4b 03 04`.
- page errors: `0`; non-blocking network warning: one `/api/v1/auth/setup-status` request returned HTTP `429` after the flow had already reached the workspace.

Repeatable browser audit:

```bash
cd /mnt/e/deerflow-agent-lab/deer-flow/frontend
corepack pnpm audit:debug-export
```

The script logs in with the local development account, opens a new chat, uploads a 1x1 PNG, types into the chat input, clicks submit, polls `/debug-export`, checks the ZIP archive, and writes `harness-workbench/browser-audit/debug-export/report.json`.

Latest script result:

```text
threadId=38471f81-c23e-40e6-98da-a8f17c4a40d7
eventCount=25
redactionCount=9
redactionMarkerCount=9
redactionReportPathMismatch=false
hostPathLeak=false
archive.magic=50 4b 03 04
uiDownloads=debug-export-ui.json(schema=1,redactionCount=9,redactionMarkerCount=9,hostPathLeak=false),debug-export-ui.zip(magic=50 4b 03 04)
networkFailures=1(setup-status 429)
pageErrors=0
reportFile=/mnt/e/deerflow-agent-lab/harness-workbench/browser-audit/debug-export/report.json
```

Coverage limits:

- The real provider run above persisted hidden reasoning-like fields; the live export reported `redaction_report.hidden_chain_of_thought.count=9`.
- Positive hidden-field redaction is also covered by backend tests using persisted event payloads containing `reasoning_content` and `thinking`.
- Raw hidden chain-of-thought is intentionally not exported. Development researchers should use visible messages, tool traces, token usage, files, and `redaction_report` paths/counts to study behavior without exposing hidden model deliberation.
