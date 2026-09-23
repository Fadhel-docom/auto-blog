#!/usr/bin/env python3

import json
import os

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT_DIR / "logs"
AI_DIR = LOG_DIR / "ai_suggestions"

HEALTH_PATH = LOG_DIR / "health.json"
UI_REPORT_PATH = LOG_DIR / "ui_report.json"
UI_SUGGESTIONS_PATH = LOG_DIR / "ui_suggestions.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-4o-mini",
).strip()

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

TIMEOUT = 60
MAX_CONTEXT_CHARS = 45000


def now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def load_json(path: Path) -> Any:
    if not path.exists():
        return {"_missing": str(path)}

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        return {
            "_error": str(exc),
            "_path": str(path),
        }


def collect_logs() -> dict[str, Any]:
    result = {}

    for path in sorted(LOG_DIR.glob("*.json")):
        if path.name in {
            "health.json",
            "ui_report.json",
            "ui_suggestions.json",
        }:
            continue

        try:
            result[path.name] = json.loads(
                path.read_text(encoding="utf-8")
            )
        except Exception:
            result[path.name] = {"unreadable": True}

    return result


def build_context() -> dict[str, Any]:
    context = {
        "timestamp": now(),
        "health": load_json(HEALTH_PATH),
        "ui_report": load_json(UI_REPORT_PATH),
        "ui_suggestions": load_json(UI_SUGGESTIONS_PATH),
        "recent_logs": collect_logs(),
    }

    raw = json.dumps(
        context,
        indent=2,
        ensure_ascii=False,
    )

    if len(raw) > MAX_CONTEXT_CHARS:
        raw = raw[-MAX_CONTEXT_CHARS:]

        context = {
            "truncated_context": True,
            "raw_context_tail": raw,
        }

    return context


def system_prompt() -> str:
    return """
You are the maintenance analyst for an automated Hugo home-organization website.

Your task is NOT to rewrite the entire website and NOT to make speculative changes.

Analyze the supplied health, UI, and pipeline evidence.

Return JSON only.

Identify:

1. confirmed defects
2. probable defects
3. safe maintenance improvements
4. changes that should NOT be automated
5. concrete files likely responsible
6. validation steps

Rules:

- Never invent a file that is not evidenced by the context unless clearly marked as a proposed file.
- Prefer small deterministic fixes.
- Never expose secrets.
- Never modify credentials.
- Never recommend deleting content merely because it is old.
- Do not recommend broad redesigns without evidence.
- Treat HTTP 404, missing schema, missing metadata, broken links, failed builds, and stale pipeline state as higher priority than cosmetic improvements.
- Separate confirmed facts from hypotheses.
- A recommendation must include a reason.
- If evidence is insufficient, say so.

Required JSON structure:

{
  "summary": "...",
  "confirmed_issues": [],
  "probable_issues": [],
  "safe_improvements": [],
  "do_not_automate": [],
  "files_to_review": [],
  "validation_plan": []
}

Each issue should contain:

{
  "priority": "high|medium|low",
  "area": "...",
  "evidence": "...",
  "reason": "...",
  "recommended_action": "..."
}
""".strip()


def call_openai(
    context: dict[str, Any],
) -> dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not configured."
        )

    payload = {
        "model": OPENAI_MODEL,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": system_prompt(),
            },
            {
                "role": "user",
                "content": (
                    "Analyze this site-maintenance "
                    "context:\n\n"
                    + json.dumps(
                        context,
                        indent=2,
                        ensure_ascii=False,
                    )
                ),
            },
        ],
        "response_format": {
            "type": "json_object",
        },
    }

    response = requests.post(
        OPENAI_URL,
        headers={
            "Authorization": (
                f"Bearer {OPENAI_API_KEY}"
            ),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"OpenAI API failed: "
            f"{response.status_code} "
            f"{response.text[:1000]}"
        )

    data = response.json()
    choices = data.get("choices", [])

    if not choices:
        raise RuntimeError(
            "OpenAI returned no choices."
        )

    content = (
        choices[0]
        .get("message", {})
        .get("content", "")
    )

    if not content:
        raise RuntimeError(
            "OpenAI returned empty content."
        )

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "OpenAI returned invalid JSON."
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError(
            "AI result must be a JSON object."
        )

    return result


def save_suggestion(
    result: dict[str, Any],
) -> Path:
    AI_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = (
        datetime.now(timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )

    path = AI_DIR / f"suggestion_{timestamp}.json"

    payload = {
        "timestamp": now(),
        "model": OPENAI_MODEL,
        "result": result,
    }

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    latest = AI_DIR / "latest.json"

    latest.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


def main() -> int:
    context = build_context()

    try:
        result = call_openai(context)
        path = save_suggestion(result)

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        print(f"AI suggestion saved: {path}")

        return 0

    except Exception as exc:
        AI_DIR.mkdir(parents=True, exist_ok=True)

        error_path = AI_DIR / "latest_error.json"

        error_path.write_text(
            json.dumps(
                {
                    "timestamp": now(),
                    "model": OPENAI_MODEL,
                    "error": str(exc),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(f"AI assistant failed: {exc}")

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
