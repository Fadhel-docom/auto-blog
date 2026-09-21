#!/usr/bin/env python3

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"
IMAGE_DIR = ROOT_DIR / "static" / "images"

MIN_WORDS = 1800
MAX_WORDS = 2400

MIN_H2 = 8
MAX_H2 = 12

REQUIRED_IMAGES = 10


def load_article() -> Dict[str, Any]:
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(
            f"article.json was not found at: {ARTICLE_PATH}"
        )

    try:
        with ARTICLE_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
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


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    return value.strip()


def count_words(content: str) -> int:
    if not isinstance(content, str):
        return 0

    text = re.sub(r"`[^`]+`", " ", content)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"[#>*_~`]+", " ", text)

    words = re.findall(
        r"\b[\w'-]+\b",
        text,
        flags=re.UNICODE,
    )

    return len(words)


def extract_h2_headings(content: str) -> List[str]:
    headings = []

    in_fenced_code_block = False
    fence_marker: Optional[str] = None

    for line in content.splitlines():
        stripped = line.strip()

        if (
            stripped.startswith("```")
            or stripped.startswith("~~~")
        ):
            if not in_fenced_code_block:
                in_fenced_code_block = True

                if stripped.startswith("```"):
                    fence_marker = "```"
                else:
                    fence_marker = "~~~"

            elif (
                fence_marker
                and stripped.startswith(fence_marker)
            ):
                in_fenced_code_block = False
                fence_marker = None

            continue

        if in_fenced_code_block:
            continue

        match = re.match(
            r"^\s*##[ \t]+([^#].*?)\s*$",
            line,
        )

        if match:
            heading = match.group(1).strip()

            if heading:
                headings.append(heading)

    return headings


def extract_h1_headings(content: str) -> List[str]:
    headings = []

    in_fenced_code_block = False
    fence_marker: Optional[str] = None

    for line in content.splitlines():
        stripped = line.strip()

        if (
            stripped.startswith("```")
            or stripped.startswith("~~~")
        ):
            if not in_fenced_code_block:
                in_fenced_code_block = True

                if stripped.startswith("```"):
                    fence_marker = "```"
                else:
                    fence_marker = "~~~"

            elif (
                fence_marker
                and stripped.startswith(fence_marker)
            ):
                in_fenced_code_block = False
                fence_marker = None

            continue

        if in_fenced_code_block:
            continue

        match = re.match(
            r"^\s*#[ \t]+([^#].*?)\s*$",
            line,
        )

        if match:
            headings.append(
                match.group(1).strip()
            )

    return headings


def validate_slug(slug: str) -> bool:
    return bool(
        re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*",
            slug,
        )
    )


def check_image_file(
    image: Dict[str, Any],
    index: int,
    slug: str,
) -> Tuple[bool, str]:
    file_value = image.get("file", "")

    if not isinstance(file_value, str):
        return (
            False,
            f"Image #{index} has an invalid file field.",
        )

    file_value = file_value.strip()

    if not file_value:
        return (
            False,
            f"Image #{index} has an empty file field.",
        )

    expected_filename = f"{slug}-{index}.jpg"

    expected_path = IMAGE_DIR / expected_filename

    if not expected_path.exists():
        return (
            False,
            f"Image #{index} is missing from disk: "
            f"{expected_path}",
        )

    if expected_path.stat().st_size <= 0:
        return (
            False,
            f"Image #{index} exists but is empty: "
            f"{expected_path}",
        )

    query = image.get("query", "")

    if not isinstance(query, str) or not query.strip():
        return (
            False,
            f"Image #{index} has no valid query/alt text.",
        )

    return (True, "")


def add_warning(
    warnings: List[str],
    message: str,
) -> None:
    warnings.append(message)
    print(f"WARNING: {message}")


def add_error(
    errors: List[str],
    message: str,
) -> None:
    errors.append(message)
    print(f"ERROR: {message}", file=sys.stderr)


def main() -> int:
    print("=" * 70)
    print("COMPETITIVE SEO CHECK")
    print("=" * 70)

    warnings: List[str] = []
    errors: List[str] = []

    try:
        article = load_article()

        title = clean_text(article.get("title", ""))
        meta_description = clean_text(
            article.get("meta_description", "")
        )
        keyword = clean_text(article.get("keyword", ""))
        slug = clean_text(article.get("slug", ""))
        content = article.get("content_markdown", "")

        print(f"Title: {title}")
        print(f"Keyword: {keyword}")
        print(f"Slug: {slug}")

        if not title:
            add_error(errors, "Article title is missing.")

        if not meta_description:
            add_error(errors, "Meta description is missing.")

        if not keyword:
            add_error(errors, "Focus keyword is missing.")

        if not slug:
            add_error(errors, "Slug is missing.")
        elif not validate_slug(slug):
            add_error(errors, f"Slug is invalid: {slug}")

        if not isinstance(content, str) or not content.strip():
            add_error(
                errors,
                "content_markdown is missing or empty.",
            )
            content = ""

        words = count_words(content)
        h2_headings = extract_h2_headings(content)
        h1_headings = extract_h1_headings(content)

        print("")
        print("Content metrics:")
        print(f"  Words: {words}")
        print(f"  H2 headings: {len(h2_headings)}")
        print(
            f"  H1 headings inside content: "
            f"{len(h1_headings)}"
        )

        if words < MIN_WORDS:
            add_error(
                errors,
                f"Article has only {words} words. "
                f"Minimum target is {MIN_WORDS}.",
            )

        elif words > MAX_WORDS:
            add_warning(
                warnings,
                f"Article has {words} words. "
                f"Target maximum is {MAX_WORDS}.",
            )

        if len(h2_headings) < MIN_H2:
            add_error(
                errors,
                f"Article has only {len(h2_headings)} H2 headings. "
                f"Minimum target is {MIN_H2}.",
            )

        elif len(h2_headings) > MAX_H2:
            add_warning(
                warnings,
                f"Article has {len(h2_headings)} H2 headings. "
                f"Target maximum is {MAX_H2}.",
            )

        if h1_headings:
            add_warning(
                warnings,
                "content_markdown contains an H1. "
                "The Hugo template normally supplies "
                "the page title.",
            )

        if title and len(title) < 30:
            add_warning(
                warnings,
                f"Title is short ({len(title)} characters).",
            )

        if title and len(title) > 70:
            add_warning(
                warnings,
                f"Title is long ({len(title)} characters).",
            )

        if meta_description:
            meta_length = len(meta_description)

            print(
                f"Meta description length: "
                f"{meta_length} characters"
            )

            if meta_length < 100:
                add_warning(
                    warnings,
                    "Meta description is shorter "
                    "than 100 characters.",
                )

            if meta_length > 170:
                add_warning(
                    warnings,
                    "Meta description exceeds "
                    "170 characters.",
                )

        if keyword:
            keyword_lower = keyword.lower()

            if keyword_lower not in title.lower():
                add_error(
                    errors,
                    "Focus keyword is not present "
                    "in the title.",
                )

            first_part = content[:2000].lower()

            if keyword_lower not in first_part:
                add_warning(
                    warnings,
                    "Focus keyword was not found near "
                    "the beginning of the article.",
                )

            if keyword_lower not in content.lower():
                add_error(
                    errors,
                    "Focus keyword is not present "
                    "in article content.",
                )

        image_queries = article.get("image_queries")

        if not isinstance(image_queries, list):
            add_error(
                errors,
                "image_queries is missing or is not a list.",
            )
        else:
            print(f"Image queries: {len(image_queries)}")

            if len(image_queries) != REQUIRED_IMAGES:
                add_error(
                    errors,
                    f"Expected {REQUIRED_IMAGES} image "
                    f"queries, found {len(image_queries)}.",
                )

        images = article.get("images")

        if not isinstance(images, list):
            add_error(
                errors,
                "images is missing or is not a list.",
            )
            images = []

        print(f"Images in article.json: {len(images)}")

        if len(images) != REQUIRED_IMAGES:
            add_error(
                errors,
                f"Expected {REQUIRED_IMAGES} downloaded "
                f"images, found {len(images)}.",
            )

        valid_image_count = 0

        for index, image in enumerate(images, start=1):
            if not isinstance(image, dict):
                add_error(
                    errors,
                    f"Image #{index} is not an object.",
                )
                continue

            valid, message = check_image_file(
                image,
                index,
                slug,
            )

            if valid:
                valid_image_count += 1
            else:
                add_error(errors, message)

        print(
            f"Valid image files: "
            f"{valid_image_count}/{REQUIRED_IMAGES}"
        )

        if valid_image_count == 0:
            add_error(
                errors,
                "No valid article images were found.",
            )

        elif valid_image_count < REQUIRED_IMAGES:
            add_error(
                errors,
                "Not all competitive article images "
                "are available.",
            )

        tags = article.get("tags", [])

        if not isinstance(tags, list) or not tags:
            add_warning(
                warnings,
                "Article has no tags.",
            )

        print("")
        print("H2 structure:")

        for index, heading in enumerate(h2_headings, start=1):
            print(f"  {index}. {heading}")

        print("")
        print(f"Warnings: {len(warnings)}")
        print(f"Errors: {len(errors)}")

        if errors:
            print("")
            print("SEO CHECK FAILED.")
            print(
                "The article is not safe to pass "
                "to the publishing stage.",
                file=sys.stderr,
            )
            print("=" * 70)
            return 1

        print("")
        print("SEO CHECK PASSED.")

        if warnings:
            print("The warnings above are non-blocking.")
        else:
            print("No warnings detected.")

        print("=" * 70)
        print("COMPETITIVE SEO CHECK COMPLETE")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print("", file=sys.stderr)
        print("Operation cancelled.", file=sys.stderr)
        return 130

    except Exception as exc:
        print("", file=sys.stderr)
        print("COMPETITIVE SEO CHECK FAILED", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
