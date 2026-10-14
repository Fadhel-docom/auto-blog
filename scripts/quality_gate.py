#!/usr/bin/env python3
"""Standalone editorial quality gate.

# Validates the current editorial target without relaxing publish_guard criteria.
# The fallback uses recent Git history so script-only pushes still validate the latest article.

On a push, validate the post changed by that push. This prevents an unrelated
legacy article from blocking closure of a newly edited article while retaining
the full publish_guard criteria for the target post.
"""
from pathlib import Path
import importlib.util
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

GUARD = Path(__file__).with_name("publish_guard.py")
if not GUARD.is_file():
    raise SystemExit("QUALITY GATE: publish_guard.py not found")

LINK_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)
SOURCES_RE = re.compile(
    r"^##+\s+(?:Sources|References)\b[^\n]*\n(.*?)(?=^##\s|\Z)", re.M | re.S | re.I
)
LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)|<(https?://[^>\s]+)>")


def source_links(post_path):
    """External links inside the post's Sources section; None if there is no such section."""
    text = Path(post_path).read_text(encoding="utf-8")
    match = SOURCES_RE.search(text)
    if not match:
        return None
    links = []
    for md_url, auto_url in LINK_RE.findall(match.group(1)):
        url = md_url or auto_url
        if url not in links:
            links.append(url)
    return links


def fetch_status(url, attempts=2, timeout=30):
    """Return (status_code, detail). status_code is None when the server never answered."""
    last = "no response"
    for _ in range(attempts):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": LINK_UA, "Accept": "text/html,application/pdf,*/*"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, "OK"
        except urllib.error.HTTPError as exc:
            return exc.code, str(exc.reason)
        except Exception as exc:  # DNS failure, timeout, TLS error...
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2)
    return None, last


def check_source_links(post_path):
    """HTTP-check every link in the Sources section. Any 4xx/5xx or no answer = FAIL."""
    name = Path(post_path).name
    links = source_links(post_path)
    if links is None:
        print(f"SOURCE LINKS: no Sources section in {name}; nothing to check")
        return True
    if not links:
        print(f"SOURCE LINKS: Sources section of {name} has no links")
        return True
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda u: (u, *fetch_status(u)), links))
    failed = 0
    for url, status, detail in results:
        if status is None or status >= 400:
            failed += 1
            print(f"  {status if status is not None else 'ERR'} {url}  <- {detail}")
        else:
            print(f"  {status} {url}")
    if failed:
        print(f"SOURCE LINKS: FAIL {name} ({failed} of {len(links)} links)")
        return False
    print(f"SOURCE LINKS: OK {name} ({len(links)} links)")
    return True


def latest_post():
    """Same selection publish_guard makes when it is run without a target."""
    spec = importlib.util.spec_from_file_location("publish_guard", GUARD)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    posts = [p for p in guard.POSTS.glob("*.md") if p.name != ".gitkeep"]
    if not posts:
        return None
    return max(posts, key=lambda p: guard.post_date(p.read_text(encoding="utf-8")))


target = None
event = os.environ.get("GITHUB_EVENT_NAME", "")
if event == "push":
    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD^", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    changed_posts = [
        line.strip() for line in diff.stdout.splitlines()
        if line.startswith("content/posts/") and line.endswith(".md")
    ]
    if not changed_posts:
        history = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", "content/posts"],
            capture_output=True, text=True, check=False,
        )
        if history.stdout.strip():
            latest_content_commit = history.stdout.strip()
            files = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", latest_content_commit, "--", "content/posts"],
                capture_output=True, text=True, check=False,
            )
            changed_posts = [
                line.strip() for line in files.stdout.splitlines()
                if line.startswith("content/posts/") and line.endswith(".md")
            ]

    if changed_posts:
        if len(changed_posts) > 1:
            print("QUALITY GATE: multiple changed posts; validating each")
            for post in changed_posts:
                result = subprocess.run([sys.executable, str(GUARD), post], check=False)
                if result.returncode != 0:
                    print(f"QUALITY GATE: BLOCKED ({post})")
                    sys.exit(result.returncode)
                if not check_source_links(post):
                    print(f"QUALITY GATE: BLOCKED ({post}: source links)")
                    sys.exit(1)
            print("QUALITY GATE: PASS")
            sys.exit(0)
        target = changed_posts[0]

cmd = [sys.executable, str(GUARD)]
if target:
    cmd.append(target)

result = subprocess.run(cmd, check=False)
if result.returncode == 0:
    link_target = target or latest_post()
    if link_target is not None and not check_source_links(link_target):
        print(f"QUALITY GATE: BLOCKED ({link_target}: source links)")
        sys.exit(1)
    print("QUALITY GATE: PASS")
else:
    print(f"QUALITY GATE: BLOCKED (publish_guard exit={result.returncode})")
sys.exit(result.returncode)
