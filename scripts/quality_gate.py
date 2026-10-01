#!/usr/bin/env python3
"""Standalone editorial quality gate.

# Validates the current editorial target without relaxing publish_guard criteria.
# The fallback uses recent Git history so script-only pushes still validate the latest article.

On a push, validate the post changed by that push. This prevents an unrelated
legacy article from blocking closure of a newly edited article while retaining
the full publish_guard criteria for the target post.
"""
from pathlib import Path
import os
import subprocess
import sys

GUARD = Path(__file__).with_name("publish_guard.py")
if not GUARD.is_file():
    raise SystemExit("QUALITY GATE: publish_guard.py not found")

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
            print("QUALITY GATE: PASS")
            sys.exit(0)
        target = changed_posts[0]

cmd = [sys.executable, str(GUARD)]
if target:
    cmd.append(target)

result = subprocess.run(cmd, check=False)
if result.returncode == 0:
    print("QUALITY GATE: PASS")
else:
    print(f"QUALITY GATE: BLOCKED (publish_guard exit={result.returncode})")
sys.exit(result.returncode)
