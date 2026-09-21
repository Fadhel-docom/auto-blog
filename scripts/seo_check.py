#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"


def load_article():
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(
            f"article.json not found: {ARTICLE_PATH}"
        )

    with ARTICLE_PATH.open(
        "r", encoding="utf-8"
    ) as file:
        article = json.load(file)

    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain a JSON object."
        )

    return article


def count_words(text):
    plain = re.sub(r"[!\[\]()]+", " ", text)
    plain = re.sub(r"`[^`]+`", "", plain)

    return len(
        re.findall(
            r"\b[\w'-]+\b",
            plain,
            flags=re.UNICODE,
        )
    )


def main() -> int:
    print("=" * 70)
    print("SEO CHECK (warning mode)")
    print("=" * 70)

    try:
        article = load_article()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    warnings = []

    keyword = str(article.get("keyword", "")).strip()
    title = str(article.get("title", "")).strip()
    meta = str(article.get("meta_description", "")).strip()
    content = str(article.get("content_markdown", "")).strip()
    slug = str(article.get("slug", "")).strip()

    # --------------------------------------------------------
    # Required fields
    # --------------------------------------------------------
    required = [
        "keyword", "title", "slug",
        "meta_description", "content_markdown",
        "image_queries", "tags",
    ]

    for field in required:
        if field not in article:
            warnings.append(f"Missing field: {field}")

    # --------------------------------------------------------
    # Title length
    # --------------------------------------------------------
    title_length = len(title)
    print(f"Title length: {title_length}")

    if title_length < 20:
        warnings.append(
            f"Title too short: {title_length}"
        )
    elif title_length > 120:
        warnings.append(
            f"Title too long: {title_length}"
        )

    # --------------------------------------------------------
    # Slug
    # --------------------------------------------------------
    print(f"Slug: {slug}")

    if slug and slug.split("-")[-1] in {
        "for", "to", "of", "the", "a", "an",
        "in", "on", "at", "and", "or", "with",
    }:
        warnings.append(
            f"Slug ends with stop word: {slug}"
        )

    # --------------------------------------------------------
    # Meta description
    # --------------------------------------------------------
    meta_length = len(meta)
    print(f"Meta length: {meta_length}")

    if meta_length < 100:
        warnings.append(
            f"Meta too short: {meta_length}"
        )
    elif meta_length > 200:
        warnings.append(
            f"Meta too long: {meta_length}"
        )

    # --------------------------------------------------------
    # H2 count
    # --------------------------------------------------------
    h2_count = len(
        re.findall(
            r"^\s*##\s+\S+",
            content,
            flags=re.MULTILINE,
        )
    )

    print(f"H2 count: {h2_count}")

    if h2_count < 3:
        warnings.append(
            f"Too few H2: {h2_count}"
        )

    # --------------------------------------------------------
    # Word count
    # --------------------------------------------------------
    words = count_words(content)
    print(f"Word count: {words}")

    if words < 800:
        warnings.append(
            f"Too short: {words} words"
        )
    elif words > 2800:
        warnings.append(
            f"Too long: {words} words"
        )

    # --------------------------------------------------------
    # Keyword in title
    # --------------------------------------------------------
    if keyword:
        if keyword.lower() not in title.lower():
            warnings.append(
                "Keyword not in title"
            )

        intro = content[:1500].lower()
        if keyword.lower() not in intro:
            warnings.append(
                "Keyword not in introduction"
            )

    # --------------------------------------------------------
    # Image queries
    # --------------------------------------------------------
    image_queries = article.get("image_queries")

    if isinstance(image_queries, list):
        print(f"Image queries: {len(image_queries)}")
        if len(image_queries) != 5:
            warnings.append(
                f"Expected 5 image queries, "
                f"got {len(image_queries)}"
            )

    # --------------------------------------------------------
    # Placeholders
    # --------------------------------------------------------
    placeholder_patterns = [
        r"\[insert[^\]]*\]",
        r"\bTODO\b",
        r"\bTBD\b",
        r"\bPLACEHOLDER\b",
        r"\bLOREM\s+IPSUM\b",
    ]

    for pattern in placeholder_patterns:
        if re.search(
            pattern,
            content,
            flags=re.IGNORECASE,
        ):
            warnings.append(
                f"Placeholder found: {pattern}"
            )
            break

    # --------------------------------------------------------
    # Final result
    # --------------------------------------------------------
    print("")

    if warnings:
        print("WARNINGS (continuing anyway):")
        for index, warning in enumerate(
            warnings, start=1
        ):
            print(f"  {index}. {warning}")
    else:
        print("SEO CHECK PASSED")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
