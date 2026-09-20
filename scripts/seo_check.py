#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"


def load_article() -> Dict[str, Any]:
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(
            f"article.json was not found at: {ARTICLE_PATH}"
        )
    try:
        with ARTICLE_PATH.open("r", encoding="utf-8") as file:
            article = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"article.json contains invalid JSON: {exc}"
        ) from exc
    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain a JSON object."
        )
    return article


def clean_text(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"[*_~>#]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def word_count(text: str) -> int:
    return len(
        re.findall(
            r"\b[\w'-]+\b",
            text,
            flags=re.UNICODE,
        )
    )


def get_introduction(content: str) -> str:
    lines = content.splitlines()
    introduction_lines: List[str] = []

    for line in lines:
        if re.match(r"^\s*##\s+", line):
            break
        introduction_lines.append(line)

    introduction = "\n".join(introduction_lines)
    return clean_text(introduction)


def contains_placeholders(text: str) -> List[str]:
    patterns = [
        r"\[insert[^\]]*\]",
        r"\[INSERT[^\]]*\]",
        r"\bTODO\b",
        r"\bTBD\b",
        r"\bPLACEHOLDER\b",
        r"\bLOREM\s+IPSUM\b",
        r"<insert[^>]*>",
        r"\{\{[^}]+\}\}",
        r"\[\s*your\s+[^]]+\]",
        r"\[\s*add\s+[^]]+\]",
        r"\[\s*replace\s+[^]]+\]",
    ]

    matches: List[str] = []

    for pattern in patterns:
        found = re.findall(
            pattern,
            text,
            flags=re.IGNORECASE,
        )
        for item in found:
            if item not in matches:
                matches.append(item)

    return matches


def check_required_fields(
    article: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    required_fields = [
        "keyword",
        "title",
        "slug",
        "meta_description",
        "content_markdown",
        "image_query",
        "tags",
    ]
    for field in required_fields:
        if field not in article:
            errors.append(f"Missing required field: {field}")
    return errors


def main() -> int:
    print("=" * 70)
    print("SEO CHECK")
    print("=" * 70)

    try:
        article = load_article()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    errors: List[str] = []

    errors.extend(check_required_fields(article))

    if errors:
        print("\nFAILED")
        for error in errors:
            print(f" - {error}")
        return 1

    keyword = str(article.get("keyword", "")).strip()
    title = str(article.get("title", "")).strip()
    meta_description = str(
        article.get("meta_description", "")
    ).strip()
    content = str(
        article.get("content_markdown", "")
    ).strip()

    title_length = len(title)
    print(
        f"\nTitle length: {title_length} characters"
    )
    if not 30 <= title_length <= 65:
        errors.append(
            "Title length must be between "
            "30 and 65 characters."
        )
    else:
        print(" PASS")

    h2_matches = re.findall(
        r"^\s*##\s+\S+",
        content,
        flags=re.MULTILINE,
    )
    print(f"\nH2 headings found: {len(h2_matches)}")
    if not h2_matches:
        errors.append(
            "The article must contain at least one H2 heading."
        )
    else:
        print(" PASS")

    meta_length = len(meta_description)
    print(
        f"\nMeta description length: "
        f"{meta_length} characters"
    )
    if not 140 <= meta_length <= 160:
        errors.append(
            "Meta description length must be "
            "between 140 and 160 characters."
        )
    else:
        print(" PASS")

    if not keyword:
        errors.append("Keyword is empty.")
    else:
        keyword_in_title = (
            keyword.casefold() in title.casefold()
        )
        print(
            f"\nKeyword in title: "
            f"{'YES' if keyword_in_title else 'NO'}"
        )
        if not keyword_in_title:
            errors.append(
                "The focus keyword must appear in the title."
            )
        else:
            print(" PASS")

    introduction = get_introduction(content)
    keyword_in_intro = False

    if keyword:
        keyword_in_intro = (
            keyword.casefold() in introduction.casefold()
        )

    print(
        f"\nKeyword in introduction: "
        f"{'YES' if keyword_in_intro else 'NO'}"
    )
    if not keyword_in_intro:
        errors.append(
            "The focus keyword must appear in the introduction."
        )
    else:
        print(" PASS")

    searchable_text = (
        f"{title}\n"
        f"{meta_description}\n"
        f"{content}"
    )
    placeholders = contains_placeholders(searchable_text)
    print(f"\nPlaceholders found: {len(placeholders)}")
    if placeholders:
        errors.append(
            "Placeholder text was found: "
            + ", ".join(placeholders)
        )
    else:
        print(" PASS")

    content_words = word_count(clean_text(content))
    print(f"\nArticle word count: {content_words}")
    if not 1200 <= content_words <= 1900:
        errors.append(
            "Article content should contain "
            "between 1200 and 1900 words."
        )
    else:
        print(" PASS")

    print("")
    print("=" * 70)

    if errors:
        print("SEO CHECK FAILED")
        print("=" * 70)
        for index, error in enumerate(errors, start=1):
            print(f"{index}. {error}")
        print("\nExit code: 1")
        return 1

    print("SEO CHECK PASSED")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
