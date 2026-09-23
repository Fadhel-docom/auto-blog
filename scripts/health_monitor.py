#!/usr/bin/env python3

import csv
import json
import os
import re
import subprocess

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]

SITE_URL = os.getenv(
    "SITE_URL",
    "https://fadhel-docom.github.io/auto-blog/",
).rstrip("/") + "/"

REPO = os.getenv(
    "GITHUB_REPOSITORY",
    "Fadhel-docom/auto-blog",
)

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

KEYWORDS_PATH = ROOT_DIR / "keywords.csv"
IMAGE_DIR = ROOT_DIR / "static" / "images"
LOG_DIR = ROOT_DIR / "logs"
HEALTH_PATH = LOG_DIR / "health.json"

REQUEST_TIMEOUT = 20
MAX_RUNS = 20
MAX_LINKS = 20


def now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def headers() -> dict[str, str]:
    result = {
        "User-Agent": "auto-blog-health-monitor",
    }

    if GITHUB_TOKEN:
        result["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    return result


def request(
    url: str,
    method: str = "GET",
) -> requests.Response:
    return requests.request(
        method,
        url,
        headers=headers(),
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    )


def github_json(
    path: str,
    **kwargs: Any,
) -> Any:
    response = requests.get(
        f"{GITHUB_API}{path}",
        headers={
            **headers(),
            "Accept": "application/vnd.github+json",
        },
        timeout=REQUEST_TIMEOUT,
        **kwargs,
    )

    if not response.ok:
        raise RuntimeError(
            f"GitHub API failed: {response.status_code}"
        )

    return response.json()


def ensure_logs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def check_url(url: str) -> dict[str, Any]:
    try:
        response = request(url)

        return {
            "url": url,
            "status": response.status_code,
            "final_url": response.url,
            "ok": 200 <= response.status_code < 400,
            "content_type": response.headers.get(
                "content-type", "",
            ),
        }

    except Exception as exc:
        return {
            "url": url,
            "status": None,
            "final_url": None,
            "ok": False,
            "error": str(exc),
        }


def fetch_home() -> str:
    response = request(SITE_URL)

    if not response.ok:
        raise RuntimeError(
            f"Home page returned {response.status_code}"
        )

    return response.text


def extract_internal_links(html: str) -> list[str]:
    links = re.findall(
        r'href=["\']([^"\']+)["\']',
        html,
        flags=re.IGNORECASE,
    )

    result = []

    for href in links:
        if href.startswith("#"):
            continue

        if href.startswith(
            ("mailto:", "javascript:", "tel:")
        ):
            continue

        absolute = urljoin(SITE_URL, href)
        parsed = urlparse(absolute)

        if parsed.netloc != urlparse(SITE_URL).netloc:
            continue

        clean = (
            f"{parsed.scheme}://"
            f"{parsed.netloc}"
            f"{parsed.path}"
        )

        if clean not in result:
            result.append(clean)

    return result[:MAX_LINKS]


def check_site_links() -> dict[str, Any]:
    home = check_url(SITE_URL)

    if not home["ok"]:
        return {
            "home": home,
            "links": [],
            "broken": [home],
        }

    try:
        html = fetch_home()
        links = extract_internal_links(html)
    except Exception as exc:
        return {
            "home": home,
            "links": [],
            "broken": [{
                "url": SITE_URL,
                "error": str(exc),
            }],
        }

    checks = [check_url(link) for link in links]

    broken = [
        item for item in checks
        if not item.get("ok")
    ]

    return {
        "home": home,
        "links_checked": len(checks),
        "links": checks,
        "broken": broken,
    }


def keyword_counts() -> dict[str, Any]:
    if not KEYWORDS_PATH.exists():
        return {"error": "keywords.csv missing"}

    with KEYWORDS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    status_column = next(
        (
            field for field in (reader.fieldnames or [])
            if field.lower() in {"status", "state"}
        ),
        None,
    )

    counts = {
        "published": 0,
        "pending": 0,
        "processing": 0,
        "failed": 0,
        "other": 0,
        "total": len(rows),
    }

    if not status_column:
        return {
            "error": "status column missing",
            **counts,
        }

    for row in rows:
        status = str(
            row.get(status_column, "")
        ).strip().lower()

        if status in counts:
            counts[status] += 1
        else:
            counts["other"] += 1

    return counts


def image_health() -> dict[str, Any]:
    if not IMAGE_DIR.exists():
        return {
            "exists": False,
            "count": 0,
            "jpg": 0,
            "png": 0,
            "webp": 0,
            "missing_directory": True,
        }

    files = [
        path for path in IMAGE_DIR.iterdir()
        if path.is_file()
    ]

    extensions = {
        ".jpg": "jpg",
        ".jpeg": "jpg",
        ".png": "png",
        ".webp": "webp",
    }

    counts = {"jpg": 0, "png": 0, "webp": 0}

    for path in files:
        key = extensions.get(path.suffix.lower())

        if key:
            counts[key] += 1

    return {
        "exists": True,
        "count": len(files),
        **counts,
    }


def recent_runs() -> list[dict[str, Any]]:
    try:
        data = github_json(
            f"/repos/{REPO}/actions/runs",
            params={
                "per_page": MAX_RUNS,
                "exclude_pull_requests": "true",
            },
        )

        runs = data.get("workflow_runs", [])

        return [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "url": item.get("html_url"),
            }
            for item in runs
            if isinstance(item, dict)
        ]

    except Exception as exc:
        return [{"error": str(exc)}]


def stale_processing_keywords() -> list[str]:
    if not KEYWORDS_PATH.exists():
        return []

    with KEYWORDS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames or []

        status_column = next(
            (
                field for field in fields
                if field.lower() == "status"
            ),
            None,
        )

        keyword_column = next(
            (
                field for field in fields
                if field.lower() in {
                    "keyword",
                    "keywords",
                }
            ),
            None,
        )

        if not status_column or not keyword_column:
            return []

        return [
            str(
                row.get(keyword_column, "")
            ).strip()
            for row in reader
            if str(
                row.get(status_column, "")
            ).strip().lower() == "processing"
        ]


def repair_processing_keywords(
    keywords: list[str],
) -> bool:
    if not keywords:
        return False

    rows = []
    changed = False

    with KEYWORDS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        fields = reader.fieldnames or []
        rows = list(reader)

    status_column = next(
        (
            field for field in fields
            if field.lower() == "status"
        ),
        None,
    )

    keyword_column = next(
        (
            field for field in fields
            if field.lower() in {
                "keyword",
                "keywords",
            }
        ),
        None,
    )

    if not status_column or not keyword_column:
        return False

    target = {keyword.lower() for keyword in keywords}

    for row in rows:
        keyword = str(
            row.get(keyword_column, "")
        ).strip()

        if keyword.lower() in target:
            if str(
                row.get(status_column, "")
            ).lower() == "processing":
                row[status_column] = "pending"
                changed = True

    if not changed:
        return False

    temp = KEYWORDS_PATH.with_suffix(".health.tmp")

    with temp.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(rows)

    temp.replace(KEYWORDS_PATH)

    return True


def git_commit(message: str) -> bool:
    commands = [
        [
            "git", "config", "user.name",
            "github-actions[bot]",
        ],
        [
            "git", "config", "user.email",
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
            if (
                command[:2] == ["git", "commit"]
                and "nothing to commit" in result.stdout.lower()
            ):
                return False

            raise RuntimeError(
                result.stderr or result.stdout
            )

    return True


def create_issue(title: str, body: str) -> None:
    github_json(
        f"/repos/{REPO}/issues",
        method="POST",
        json={
            "title": title,
            "body": body,
            "labels": ["automation", "health"],
        },
    )


def main() -> int:
    ensure_logs()

    report: dict[str, Any] = {
        "timestamp": now(),
        "site": SITE_URL,
        "repository": REPO,
        "checks": {},
        "repairs": [],
        "issues": [],
    }

    try:
        report["checks"]["site"] = check_site_links()
        report["checks"]["keywords"] = keyword_counts()
        report["checks"]["images"] = image_health()
        report["checks"]["runs"] = recent_runs()

        stale = stale_processing_keywords()

        if stale:
            repaired = repair_processing_keywords(stale)

            if repaired:
                try:
                    git_commit(
                        "Health monitor: reset stale keywords"
                    )

                    report["repairs"].append({
                        "type": "processing_to_pending",
                        "keywords": stale,
                    })

                except Exception as exc:
                    report["issues"].append({
                        "type": "repair_failed",
                        "error": str(exc),
                    })

        broken = report["checks"]["site"].get(
            "broken", []
        )

        if broken:
            report["issues"].append({
                "type": "broken_internal_links",
                "count": len(broken),
                "items": broken[:20],
            })

        image_count = report["checks"]["images"].get(
            "count", 0
        )

        if image_count == 0:
            report["issues"].append({
                "type": "no_images",
            })

        failures = [
            run for run in report["checks"]["runs"]
            if run.get("conclusion") == "failure"
        ]

        if len(failures) >= 3:
            report["issues"].append({
                "type": "multiple_recent_failures",
                "count": len(failures),
            })

        HEALTH_PATH.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if report["issues"]:
            try:
                create_issue(
                    "Health Monitor detected site problems",
                    "```json\n"
                    + json.dumps(
                        report,
                        indent=2,
                        ensure_ascii=False,
                    )[:20000]
                    + "\n```",
                )
            except Exception as exc:
                report["issues"].append({
                    "type": "issue_creation_failed",
                    "error": str(exc),
                })

        HEALTH_PATH.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            )
        )

        return 0

    except Exception as exc:
        report["fatal_error"] = str(exc)

        HEALTH_PATH.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
