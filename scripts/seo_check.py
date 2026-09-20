#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"


def load_article():
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(f"Not found: {ARTICLE_PATH}")
    with ARTICLE_PATH.open("r", encoding="utf-8") as file:
        article = json.load(file)
    if not isinstance(article, dict):
        raise ValueError("Not a JSON object.")
    return article


def main() -> int:
    print("=" * 70)
    print("SEO CHECK (warning mode)")
    print("=" * 70)

    try:
        article = load_article()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    keyword = str(article.get("keyword", "")).strip()
    title = str(article.get("title", "")).strip()
    meta = str(article.get("meta_description", "")).strip()
    content = str(article.get("content_markdown", "")).strip()

    warnings = []

    if not 10 <= len(title) <= 120:
        warnings.append(f"Title length: {len(title)}")

    if not re.search(r"^\s*##\s+\S+", content, re.MULTILINE):
        warnings.append("No H2 heading found.")

    if not 50 <= len(meta) <= 300:
        warnings.append(f"Meta length: {len(meta)}")

    if keyword and keyword.lower() not in title.lower():
        warnings.append("Keyword not in title.")

    if keyword:
        intro = content[:1500].lower()
        if keyword.lower() not in intro:
            warnings.append("Keyword not in introduction.")

    word_count = len(
        re.findall(r"\b[\w'-]+\b", content, flags=re.UNICODE)
    )

    if word_count < 300:
        warnings.append(f"Too short: {word_count} words.")

    print(f"Title length: {len(title)}")
    print(f"Word count: {word_count}")
    print(f"Meta length: {len(meta)}")

    if warnings:
        print("")
        print("WARNINGS (continuing anyway):")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("")
        print("SEO CHECK PASSED")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
