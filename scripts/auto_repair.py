#!/usr/bin/env python3

import csv
import json
import os
import re
import sys
import time

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT_DIR / "logs"
KEYWORDS_PATH = ROOT_DIR / "keywords.csv"

GITHUB_API = "https://api.github.com"
REPO = os.getenv("GITHUB_REPOSITORY", "Fadhel-docom/auto-blog")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
DAILY_WORKFLOW = os.getenv("DAILY_WORKFLOW", "daily.yml")

MAX_RUNS_TO_ANALYZE = 20
MAX_CONSECUTIVE_FAILURES = 3

RATE_LIMIT_WAIT_SECONDS = int(
    os.getenv("RATE_LIMIT_WAIT_SECONDS", "90")
)

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "30")
)

DRY_RUN = os.getenv("AUTO_REPAIR_DRY_RUN", "").lower() in {
    "1",
    "true",
    "yes",
}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "auto-blog-auto-repair",
    }

    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    return headers


def github_request(
    method: str,
    path: str,
    **kwargs: Any,
) -> requests.Response:
    url = f"{GITHUB_API}{path}"

    response = requests.request(
        method,
        url,
        headers=api_headers(),
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )

    return response


def github_json(
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    response = github_request(method, path, **kwargs)

    if not response.ok:
        raise RuntimeError(
            f"GitHub API {method} {path} failed: "
            f"{response.status_code} "
            f"{response.text[:500]}"
        )

    if not response.text.strip():
        return None

    return response.json()


def write_log(
    run_id: str | int,
    data: dict[str, Any],
) -> Path:
    ensure_dirs()

    path = LOG_DIR / f"repair_{run_id}.json"

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return path


def get_failed_run(run_id: str) -> dict[str, Any]:
    data = github_json(
        "GET",
        f"/repos/{REPO}/actions/runs/{run_id}",
    )

    if not isinstance(data, dict):
        raise RuntimeError(
            "GitHub returned invalid workflow-run data."
        )

    return data


def get_run_jobs(
    run_id: str,
) -> list[dict[str, Any]]:
    data = github_json(
        "GET",
        f"/repos/{REPO}/actions/runs/{run_id}/jobs",
        params={"per_page": 100},
    )

    if not isinstance(data, dict):
        return []

    jobs = data.get("jobs", [])

    if not isinstance(jobs, list):
        return []

    return [
        job for job in jobs
        if isinstance(job, dict)
    ]


def get_job_logs(job_id: int) -> str:
    response = github_request(
        "GET",
        f"/repos/{REPO}/actions/jobs/{job_id}/logs",
    )

    if response.status_code == 404:
        return ""

    if not response.ok:
        return (
            f"[Unable to retrieve job logs: "
            f"{response.status_code}]"
        )

    return response.text


def collect_failure_logs(
    run_id: int,
) -> dict[str, Any]:
    jobs = get_run_jobs(run_id)

    result = {
        "jobs": [],
        "combined_log": "",
    }

    chunks = []

    for job in jobs:
        conclusion = str(
            job.get("conclusion", "")
        ).lower()

        if conclusion not in {
            "failure",
            "cancelled",
            "timed_out",
        }:
            continue

        job_id = job.get("id")

        if not isinstance(job_id, int):
            continue

        log_text = get_job_logs(job_id)

        result["jobs"].append({
            "id": job_id,
            "name": job.get("name"),
            "conclusion": conclusion,
            "log_length": len(log_text),
        })

        if log_text:
            chunks.append(
                f"\n===== JOB: {job.get('name')} =====\n"
                f"{log_text}"
            )

    combined = "\n".join(chunks)

    if len(combined) > 60000:
        combined = combined[-60000:]

    result["combined_log"] = combined

    return result


def classify_failure(
    log_text: str,
) -> dict[str, Any]:
    text = log_text.lower()

    patterns = {
        "keyword_missing": [
            "no pending keyword found",
            "no pending keywords",
            "keyword not found",
            "status=processing",
            "status processing",
        ],
        "json_failure": [
            "json_validate_failed",
            "json validation failed",
            "response_format",
            "invalid json",
            "not valid json",
            "unable to extract valid json",
            "missing required field",
            "validation/parsing",
            "truncatedjsonerror",
        ],
        "rate_limit": [
            "rate limit reached",
            "rate_limit_exceeded",
            "too many requests",
            "429",
            "tokens per day",
            "tpd",
            "rate limit",
        ],
        "images": [
            "pexels",
            "image not found",
            "images not found",
            "expected exactly 5 images",
            "image validation",
            "competitive_fetch",
        ],
        "seo_check": [
            "seo check failed",
            "competitive seo",
            "seo validation",
            "missing meta",
            "missing description",
            "missing title",
        ],
        "hugo": [
            "hugo",
            "public/index.html is missing",
            "failed to build",
        ],
        "internal_links": [
            "404",
            "internal link",
            "broken link",
        ],
    }

    scores = {}

    for name, needles in patterns.items():
        matches = [
            needle for needle in needles
            if needle in text
        ]

        scores[name] = {
            "matches": matches,
            "score": len(matches),
        }

    ordered = sorted(
        scores.items(),
        key=lambda item: item[1]["score"],
        reverse=True,
    )

    if ordered and ordered[0][1]["score"] > 0:
        category = ordered[0][0]
        confidence = min(
            1.0,
            ordered[0][1]["score"] / 3.0,
        )
    else:
        category = "unknown"
        confidence = 0.0

    return {
        "category": category,
        "confidence": confidence,
        "scores": scores,
    }


def load_keywords() -> tuple[
    list[dict[str, str]],
    list[str],
]:
    if not KEYWORDS_PATH.exists():
        raise FileNotFoundError(
            f"Missing {KEYWORDS_PATH}"
        )

    with KEYWORDS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(
                "keywords.csv has no header."
            )

        return (
            list(reader),
            list(reader.fieldnames),
        )


def save_keywords(
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    temp_path = KEYWORDS_PATH.with_suffix(
        ".repair.tmp"
    )

    with temp_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    temp_path.replace(KEYWORDS_PATH)


def repair_processing_keywords() -> list[str]:
    rows, fieldnames = load_keywords()

    status_column = next(
        (
            field for field in fieldnames
            if field.lower() in {
                "status",
                "state",
            }
        ),
        None,
    )

    keyword_column = next(
        (
            field for field in fieldnames
            if field.lower() in {
                "keyword",
                "keywords",
                "topic",
            }
        ),
        None,
    )

    if not status_column or not keyword_column:
        return []

    changed = []

    for row in rows:
        status = str(
            row.get(status_column, "")
        ).strip().lower()

        if status == "processing":
            keyword = str(
                row.get(keyword_column, "")
            ).strip()

            if keyword:
                row[status_column] = "pending"
                changed.append(keyword)

    if changed:
        save_keywords(rows, fieldnames)

    return changed


def find_existing_slug(
    keyword: str,
) -> str | None:
    posts_dir = ROOT_DIR / "content" / "posts"

    if not posts_dir.exists():
        return None

    normalized = re.sub(
        r"[^a-z0-9]+",
        "-",
        keyword.lower(),
    ).strip("-")

    candidates = []

    for path in posts_dir.glob("*.md"):
        slug = path.stem.lower()

        if normalized and normalized in slug:
            candidates.append(slug)

    if len(candidates) == 1:
        return candidates[0]

    return None


def repair_keyword_urls() -> list[dict[str, str]]:
    rows, fieldnames = load_keywords()

    keyword_column = next(
        (
            field for field in fieldnames
            if field.lower() in {
                "keyword",
                "keywords",
                "topic",
            }
        ),
        None,
    )

    url_column = next(
        (
            field for field in fieldnames
            if field.lower() == "url"
        ),
        None,
    )

    if not keyword_column or not url_column:
        return []

    changes = []

    base_url = (
        "https://fadhel-docom.github.io/"
        "auto-blog/posts/"
    )

    for row in rows:
        keyword = str(
            row.get(keyword_column, "")
        ).strip()

        status = str(
            row.get(
                next(
                    (
                        f for f in fieldnames
                        if f.lower() == "status"
                    ),
                    "",
                ),
                "",
            )
        ).strip().lower()

        if not keyword or status != "published":
            continue

        slug = find_existing_slug(keyword)

        if not slug:
            continue

        expected_url = f"{base_url}{slug}/"
        current_url = str(
            row.get(url_column, "")
        ).strip()

        if current_url != expected_url:
            row[url_column] = expected_url

            changes.append({
                "keyword": keyword,
                "old_url": current_url,
                "new_url": expected_url,
            })

    if changes:
        save_keywords(rows, fieldnames)

    return changes


def git_has_changes() -> bool:
    import subprocess

    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    return bool(result.stdout.strip())


def git_commit_and_push(message: str) -> bool:
    import subprocess

    if not git_has_changes():
        return False

    commands = [
        [
            "git",
            "config",
            "user.name",
            "github-actions[bot]",
        ],
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]"
            "@users.noreply.github.com",
        ],
        ["git", "add", "keywords.csv"],
        ["git", "commit", "-m", message],
        ["git", "push"],
    ]

    for command in commands:
        result = subprocess.run(
            command,
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed: {' '.join(command)}\n"
                f"{result.stdout}\n"
                f"{result.stderr}"
            )

    return True


def dispatch_daily() -> None:
    if DRY_RUN:
        return

    data = {"ref": "main"}

    response = github_request(
        "POST",
        f"/repos/{REPO}/actions/workflows/"
        f"{DAILY_WORKFLOW}/dispatches",
        json=data,
    )

    if response.status_code not in {201, 204}:
        raise RuntimeError(
            "Unable to dispatch daily workflow: "
            f"{response.status_code} "
            f"{response.text[:500]}"
        )


def create_issue(title: str, body: str) -> None:
    if DRY_RUN:
        return

    github_json(
        "POST",
        f"/repos/{REPO}/issues",
        json={
            "title": title,
            "body": body,
            "labels": ["automation", "auto-repair"],
        },
    )


def get_recent_runs() -> list[dict[str, Any]]:
    data = github_json(
        "GET",
        f"/repos/{REPO}/actions/workflows/"
        f"{DAILY_WORKFLOW}/runs",
        params={
            "per_page": MAX_RUNS_TO_ANALYZE,
            "exclude_pull_requests": "true",
        },
    )

    if not isinstance(data, dict):
        return []

    runs = data.get("workflow_runs", [])

    if not isinstance(runs, list):
        return []

    return [
        run for run in runs
        if isinstance(run, dict)
    ]


def consecutive_daily_failures(
    runs: list[dict[str, Any]],
) -> int:
    count = 0

    for run in runs:
        conclusion = str(
            run.get("conclusion", "")
        ).lower()

        if conclusion == "failure":
            count += 1
        elif conclusion == "success":
            break

    return count


def repair_failure(
    run_id: int,
    failure: dict[str, Any],
) -> dict[str, Any]:
    category = failure["category"]
    actions = []
    changed = False

    if category == "keyword_missing":
        repaired = repair_processing_keywords()

        if repaired:
            actions.append({
                "action": "reset_processing_to_pending",
                "keywords": repaired,
            })
            changed = True

    elif category == "json_failure":
        actions.append({
            "action": "retry_daily_pipeline",
            "reason": (
                "Known Groq JSON failure; "
                "daily.py already contains "
                "multi-layer retry/fallback logic."
            ),
        })

    elif category == "rate_limit":
        actions.append({
            "action": "wait_before_retry",
            "seconds": RATE_LIMIT_WAIT_SECONDS,
        })

        if not DRY_RUN:
            time.sleep(RATE_LIMIT_WAIT_SECONDS)

    elif category == "images":
        actions.append({
            "action": "retry_daily_pipeline",
            "reason": (
                "Image failures are pipeline-stage "
                "recoverable failures."
            ),
        })

    elif category == "seo_check":
        actions.append({
            "action": "retry_daily_pipeline",
            "reason": (
                "SEO validation is rerunnable "
                "after the source state is rebuilt."
            ),
        })

    elif category == "internal_links":
        url_changes = repair_keyword_urls()

        if url_changes:
            actions.append({
                "action": "repair_keyword_urls",
                "changes": url_changes,
            })
            changed = True

    if changed and not DRY_RUN:
        git_commit_and_push(
            "Auto repair: restore pipeline state"
        )

    if category != "unknown":
        if not DRY_RUN:
            dispatch_daily()

        actions.append({
            "action": "daily_workflow_dispatched",
        })

    return {
        "category": category,
        "confidence": failure["confidence"],
        "actions": actions,
    }


def main() -> int:
    ensure_dirs()

    run_id_raw = os.getenv(
        "FAILED_RUN_ID", ""
    ).strip()

    if not run_id_raw:
        print(
            "FAILED_RUN_ID is required.",
            file=sys.stderr,
        )
        return 2

    try:
        run_id = int(run_id_raw)
    except ValueError:
        print(
            "FAILED_RUN_ID must be an integer.",
            file=sys.stderr,
        )
        return 2

    started = utc_now()

    try:
        run = get_failed_run(run_id)
        failure_logs = collect_failure_logs(run_id)

        diagnosis = classify_failure(
            failure_logs["combined_log"]
        )

        repair = repair_failure(run_id, diagnosis)

        recent_runs = get_recent_runs()

        consecutive = consecutive_daily_failures(
            recent_runs
        )

        issue_created = False

        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            body = (
                "## Auto Repair escalation\n\n"
                f"- Repository: `{REPO}`\n"
                f"- Failed run: `{run_id}`\n"
                f"- Diagnosis: `{diagnosis['category']}`\n"
                f"- Confidence: "
                f"`{diagnosis['confidence']:.2f}`\n"
                f"- Consecutive failures: `{consecutive}`\n\n"
                "### Actions\n\n"
                "```json\n"
                f"{json.dumps(repair, indent=2)}\n"
                "```\n\n"
                "### Failure log excerpt\n\n"
                "```text\n"
                f"{failure_logs['combined_log'][-10000:]}\n"
                "\n```\n"
            )

            create_issue(
                "Auto Repair: 3 consecutive daily failures",
                body,
            )

            issue_created = True

        report = {
            "timestamp": started,
            "repository": REPO,
            "failed_run_id": run_id,
            "run": {
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "html_url": run.get("html_url"),
                "head_sha": run.get("head_sha"),
            },
            "diagnosis": diagnosis,
            "repair": repair,
            "recent_runs": [
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "conclusion": item.get("conclusion"),
                    "created_at": item.get("created_at"),
                }
                for item in recent_runs
            ],
            "consecutive_failures": consecutive,
            "issue_created": issue_created,
            "dry_run": DRY_RUN,
        }

        path = write_log(run_id, report)

        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"Repair report: {path}")

        return 0

    except Exception as exc:
        error_report = {
            "timestamp": started,
            "repository": REPO,
            "failed_run_id": run_id,
            "error": str(exc),
        }

        write_log(run_id, error_report)

        print(
            json.dumps(
                error_report,
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
