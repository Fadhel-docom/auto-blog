#!/usr/bin/env python3

"""Normalize and recover the generated article slug before publishing."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from slug_utils import normalize_existing_slug  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"


def slug_from_title(title: str) -> str:
    value = str(title or "").lower()
    value = re.sub(r"[^a-z0-9\s-]", "", value)
    value = re.sub(r"\s+", "-", value).strip("-")
    return value[:70].strip("-")


def write_article(article: dict) -> None:
    ARTICLE_PATH.write_text(
        json.dumps(article, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if not ARTICLE_PATH.exists():
        print(f"article.json not found: {ARTICLE_PATH}")
        return 0

    try:
        article = json.loads(ARTICLE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Could not read article.json: {exc}", file=sys.stderr)
        return 1

    if not isinstance(article, dict):
        print("article.json must contain a JSON object.", file=sys.stderr)
        return 1

    old_slug = str(article.get("slug", "")).strip()

    if not old_slug:
        title = str(article.get("title", "")).strip()
        if not title:
            print("article.json has neither slug nor title.", file=sys.stderr)
            return 1
        new_slug = slug_from_title(title)
        if not new_slug:
            print(f"Could not derive a slug from title: {title!r}", file=sys.stderr)
            return 1
        article["slug"] = new_slug
        try:
            write_article(article)
        except OSError as exc:
            print(f"Could not write article.json: {exc}", file=sys.stderr)
            return 1
        print(f"Slug recovered from title: {new_slug}")
        return 0

    new_slug = normalize_existing_slug(old_slug)
    if not new_slug:
        print(f"Slug normalization produced empty result from: {old_slug!r}", file=sys.stderr)
        return 1

    if new_slug == old_slug:
        print(f"Slug unchanged: {old_slug}")
        return 0

    article["slug"] = new_slug
    try:
        write_article(article)
    except OSError as exc:
        print(f"Could not write article.json: {exc}", file=sys.stderr)
        return 1

    print(f"Slug normalized: {old_slug} -> {new_slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
