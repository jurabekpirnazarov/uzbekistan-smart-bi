"""Generate docs/api.md from the OpenAPI schema (PLAN.md Phase 6).

Usage:  python -m app.api.docs_gen      (run from the repository root with backend/ on PYTHONPATH)
"""

from __future__ import annotations

from pathlib import Path

from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    spec = create_app().openapi()
    lines = [
        "# API",
        "",
        "_Generated from the OpenAPI schema by `python -m app.api.docs_gen`. Interactive docs: "
        "http://localhost:8000/docs_",
        "",
        "All routes are under `/api/v1`. Statistical responses carry `meta {sources[], period, unit, is_synthetic, "
        "retrieved_at}`. Errors use one model: `{code, message, details}` (404 `not_found`, 422 "
        "`validation_error`, 429 `rate_limited`). `/chat` is rate limited to 20 requests per minute per IP.",
        "",
        "| Method | Path | Summary | Parameters |",
        "|---|---|---|---|",
    ]
    for path, ops in sorted(spec["paths"].items()):
        for method, op in ops.items():
            params = ", ".join(f"`{p['name']}`" + ("" if p.get("required") else "?") for p in op.get("parameters", []))
            if "requestBody" in op:
                params = (params + ", " if params else "") + "JSON body"
            summary = op.get("summary") or op.get("operationId", "")
            lines.append(f"| {method.upper()} | `{path}` | {summary} | {params} |")
    lines += [
        "",
        "## Chat (SSE)",
        "",
        "`POST /api/v1/chat` with `{messages: [{role, content}]}` streams server-sent events:",
        "",
        "| Event | Data |",
        "|---|---|",
        "| `tool_call` | `{name, label, args}` — a tool the agent is calling |",
        "| `tool_result` | `{name, ok}` |",
        "| `token` | `{text}` — a piece of the markdown answer |",
        "| `verification` | `{checked, unsupported[]}` — numbers not found in any tool result |",
        "| `result` | `{request_id, map_focus{level, soatos[], region}, recommendation, is_synthetic}` |",
        "| `done` | `{tools[], mode}` — `mode` is `llm` or `fallback` (no OpenAI key) |",
        "| `error` | `{message}` |",
        "",
        "## Example",
        "",
        "```powershell",
        'curl -X POST http://localhost:8000/api/v1/recommend -H "Content-Type: application/json" '
        '-d "{\\"business_type\\":\\"pharmacy\\",\\"region\\":\\"1730\\"}"',
        "```",
        "",
    ]
    (ROOT / "docs" / "api.md").write_text("\n".join(lines), encoding="utf-8")
    print("docs/api.md written")


if __name__ == "__main__":
    main()
