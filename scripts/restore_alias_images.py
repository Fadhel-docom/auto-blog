#!/usr/bin/env python3
"""Restore article-local image aliases without changing article files."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "content" / "posts"
IMAGES_DIR = ROOT / "static" / "images"
REPORT_PATH = ROOT / "reports" / "alias_images_report.md"

ALIAS_RE = re.compile(
    r"""(?P<path>
        (?:(?:https://fadhel-docom\.github\.io)?/auto-blog/|
           https://fadhel-docom\.github\.io/|
           /auto-blog/|
           /|
           (?:\.\./)+|
           )
        images/
        (?P<alias>[A-Za-z0-9._%+@-]+--alias--[A-Za-z0-9._%+@-]+\.(?:jpg|jpeg|png|webp))
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def find_alias_references() -> list[tuple[str, str]]:
    references: set[tuple[str, str]] = set()

    posts = sorted(POSTS_DIR.rglob("*.md")) if POSTS_DIR.exists() else []
    for post in posts:
        text = post.read_text(encoding="utf-8")
        for match in ALIAS_RE.finditer(text):
            references.add((str(post.relative_to(POSTS_DIR)), match.group("alias")))

    return sorted(references)


def restore_aliases(references: list[tuple[str, str]], apply: bool):
    planned: list[tuple[str, str, str]] = []
    copied: list[tuple[str, str, str]] = []
    existing: list[tuple[str, str, str]] = []
    missing: list[tuple[str, str, str]] = []

    for post_name, alias_name in references:
        separator = "--alias--"
        source_name = alias_name.split(separator, 1)[1]
        source = IMAGES_DIR / source_name
        alias = IMAGES_DIR / alias_name

        if not source.is_file():
            missing.append((post_name, source_name, alias_name))
            continue

        if alias.exists():
            existing.append((post_name, source_name, alias_name))
            continue

        planned.append((post_name, source_name, alias_name))
        if apply:
            shutil.copy2(source, alias)
            copied.append((post_name, source_name, alias_name))

    return planned, copied, existing, missing


def write_report(
    references: list[tuple[str, str]],
    planned: list[tuple[str, str, str]],
    copied: list[tuple[str, str, str]],
    existing: list[tuple[str, str, str]],
    missing: list[tuple[str, str, str]],
    apply: bool,
) -> None:
    mode = "apply" if apply else "dry-run"
    lines = [
        "# Alias Images Report",
        "",
        f"- Mode: **{'apply' if apply else 'dry-run'}**",
        f"- Alias references found: **{len(references)}**",
        f"- Alias copies planned: **{len(planned)}**",
        f"- Alias copies done: **{len(copied)}**",
        f"- Existing aliases left untouched: **{len(existing)}**",
        f"- Missing source images: **{len(missing)}**",
        "",
        "## Copies done/planned",
        "",
    ]

    copies = copied if apply else planned
    if copies:
        for post_name, source_name, alias_name in copies:
            lines.append(
                f"- \x60{post_name}\x60: \x60{source_name}\x60 -> \x60{alias_name}\x60"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Existing aliases left untouched", ""])
    if existing:
        for post_name, source_name, alias_name in existing:
            lines.append(
                f"- \x60{post_name}\x60: \x60{source_name}\x60 -> \x60{alias_name}\x60 (already exists)"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Missing source images", ""])
    if missing:
        for post_name, source_name, alias_name in missing:
            lines.append(
                f"- \x60{post_name}\x60: alias \x60{alias_name}\x60 -> missing source \x60{source_name}\x60"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Article files are never modified by this script.",
            "- Existing alias files are never overwritten.",
            "",
        ]
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore missing article-local image alias files."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Copy missing aliases from their source images.",
    )
    args = parser.parse_args()

    references = find_alias_references()
    planned, copied, existing, missing = restore_aliases(references, args.apply)

    write_report(
        references=references,
        planned=planned,
        copied=copied,
        existing=existing,
        missing=missing,
        apply=args.apply,
    )

    print(f"Alias references found: {len(references)}")
    print(f"Alias copies planned: {len(planned)}")
    print(f"Alias copies done: {len(copied)}")
    print(f"Existing aliases left untouched: {len(existing)}")
    print(f"Missing source images: {len(missing)}")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
