#!/usr/bin/env python3

"""
normalize_slug.py — P0-1

Re-normalize article.json's slug after generate_post.py
runs, so that inconsistent title inputs
("5-ft", "5 ft", "5‑ft") always produce the same slug
("5ft").

Runs as a small step in daily.yml between
"Generate article" and "Publish Hugo post".
"""

import json
import sys

from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

from slug_utils import normalize_existing_slug  # noqa: E402


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"


def main() -> int:
    if not ARTICLE_PATH.exists():
        print(
            f"article.json not found: {ARTICLE_PATH}"
        )
        return 0

    try:
        article = json.loads(
            ARTICLE_PATH.read_text(encoding="utf-8")
        )
    except Exception as exc:
        print(
            f"Could not read article.json: {exc}",
            file=sys.stderr,
        )
        return 1

    if not isinstance(article, dict):
        print(
            "article.json must contain a JSON object.",
            file=sys.stderr,
        )
        return 1

    old_slug = str(
        article.get("slug", "")
    ).strip()

    if not old_slug:
        print(
            "article.json has no slug — nothing to do."
        )
        return 0

    new_slug = normalize_existing_slug(old_slug)

    if not new_slug:
        print(
            f"Slug normalization produced empty "
            f"result from: {old_slug!r}",
            file=sys.stderr,
        )
        return 1

    if new_slug == old_slug:
        print(f"Slug unchanged: {old_slug}")
        return 0

    article["slug"] = new_slug

    temp_path = ARTICLE_PATH.with_suffix(
        ".slug.tmp"
    )

    try:
        temp_path.write_text(
            json.dumps(
                article,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        temp_path.replace(ARTICLE_PATH)
    except OSError as exc:
        print(
            f"Could not write article.json: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        f"Slug normalized: {old_slug} -> {new_slug}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
