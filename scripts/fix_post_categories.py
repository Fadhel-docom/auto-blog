#!/usr/bin/env python3

"""
fix_post_categories.py — P0-2

Rewrites the `categories = [...]` line inside a Hugo
TOML frontmatter so that each post belongs to exactly
ONE canonical category.

Modes:
    default      — processes the post referenced by
                   article.json (the one just published)
    --all        — scans every file in content/posts/
                   (useful for one-shot migration)

Usage:
    python scripts/fix_post_categories.py
    python scripts/fix_post_categories.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

from category_utils import detect_category  # noqa: E402


ROOT_DIR = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT_DIR / "content" / "posts"
ARTICLE_PATH = ROOT_DIR / "article.json"

FRONTMATTER_RE = re.compile(
    r"^\+\+\+\s*\n(.*?)\n\+\+\+\s*\n",
    flags=re.DOTALL,
)


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_file(path: Path, content: str) -> None:
    temp = path.with_suffix(".cat.tmp")

    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def to_toml_string(value: str) -> str:
    value = str(value)
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", " ")

    return f'"{value}"'


def to_toml_array(values: list[str]) -> str:
    return (
        "["
        + ", ".join(
            to_toml_string(v) for v in values
        )
        + "]"
    )


def extract_field(
    frontmatter: str,
    field: str,
) -> str | None:
    pattern = re.compile(
        rf'^\s*{field}\s*=\s*"((?:\\.|[^"])*)"',
        flags=re.MULTILINE,
    )

    match = pattern.search(frontmatter)

    if not match:
        return None

    return match.group(1).replace('\\"', '"')


def extract_tags(frontmatter: str) -> list[str]:
    pattern = re.compile(
        r"^\s*tags\s*=\s*\[(.*?)\]",
        flags=re.MULTILINE | re.DOTALL,
    )

    match = pattern.search(frontmatter)

    if not match:
        return []

    inner = match.group(1)

    return [
        s.replace('\\"', '"')
        for s in re.findall(r'"((?:\\.|[^"])*)"', inner)
    ]


def replace_categories(
    frontmatter: str,
    new_categories: list[str],
) -> str:
    """
    Replace or inject the categories array inside the
    frontmatter block. Returns the new frontmatter.
    """
    replacement = (
        f"categories = "
        f"{to_toml_array(new_categories)}"
    )

    pattern = re.compile(
        r"^\s*categories\s*=\s*\[.*?\]",
        flags=re.MULTILINE | re.DOTALL,
    )

    if pattern.search(frontmatter):
        return pattern.sub(
            replacement,
            frontmatter,
            count=1,
        )

    # No categories field — insert before faq/draft if present
    insert_pattern = re.compile(
        r"^(draft\s*=.*)$",
        flags=re.MULTILINE,
    )

    if insert_pattern.search(frontmatter):
        return insert_pattern.sub(
            replacement + "\n\\1",
            frontmatter,
            count=1,
        )

    # Last resort: append at the end
    return frontmatter.rstrip() + "\n" + replacement


def process_post(
    path: Path,
    keyword: str = "",
    dry_run: bool = False,
) -> bool:
    content = read_file(path)

    fm_match = FRONTMATTER_RE.match(content)

    if not fm_match:
        print(
            f"  ! no TOML frontmatter: {path.name}",
            file=sys.stderr,
        )
        return False

    frontmatter = fm_match.group(1)
    body = content[fm_match.end():]

    title = (
        extract_field(frontmatter, "title") or ""
    )
    tags = extract_tags(frontmatter)

    new_category = detect_category(
        keyword=keyword,
        title=title,
        tags=tags,
    )

    new_frontmatter = replace_categories(
        frontmatter,
        [new_category],
    )

    if new_frontmatter == frontmatter:
        print(
            f"  · {path.name}: already "
            f"[{new_category}]"
        )
        return False

    print(
        f"  · {path.name}: -> [{new_category}]"
    )

    if dry_run:
        return True

    write_file(
        path,
        "+++\n" + new_frontmatter + "\n+++\n" + body,
    )

    return True


def get_published_slug() -> str:
    if not ARTICLE_PATH.exists():
        return ""

    try:
        article = json.loads(
            ARTICLE_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        return ""

    if not isinstance(article, dict):
        return ""

    return str(article.get("slug", "")).strip()


def get_published_keyword() -> str:
    if not ARTICLE_PATH.exists():
        return ""

    try:
        article = json.loads(
            ARTICLE_PATH.read_text(encoding="utf-8")
        )
    except Exception:
        return ""

    if not isinstance(article, dict):
        return ""

    return str(article.get("keyword", "")).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every post in content/posts/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without writing",
    )
    args = parser.parse_args()

    if not POSTS_DIR.exists():
        print(
            f"Missing {POSTS_DIR}",
            file=sys.stderr,
        )
        return 1

    if args.all:
        posts = sorted(POSTS_DIR.glob("*.md"))

        if not posts:
            print("No posts found.")
            return 0

        print(
            f"Processing all {len(posts)} posts…"
        )

        changed = 0

        for path in posts:
            if process_post(
                path,
                keyword="",
                dry_run=args.dry_run,
            ):
                changed += 1

        print(f"Done. {changed} post(s) updated.")
        return 0

    # Single-post mode
    slug = get_published_slug()

    if not slug:
        print(
            "No slug in article.json — nothing to do."
        )
        return 0

    keyword = get_published_keyword()
    path = POSTS_DIR / f"{slug}.md"

    if not path.exists():
        print(
            f"Post not found: {path}",
            file=sys.stderr,
        )
        return 1

    changed = process_post(
        path,
        keyword=keyword,
        dry_run=args.dry_run,
    )

    print(
        "Post updated."
        if changed
        else "Post already canonical."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
