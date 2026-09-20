#!/usr/bin/env python3

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"
POSTS_DIR = ROOT_DIR / "content" / "posts"
IMAGE_DIR = ROOT_DIR / "static" / "images"
KEYWORDS_PATH = ROOT_DIR / "keywords.csv"


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


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not slug:
        raise ValueError("Slug cannot be empty.")
    if not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*",
        slug,
    ):
        raise ValueError(f"Invalid slug: {slug}")
    return slug


def toml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def toml_array(values: List[str]) -> str:
    return "[" + ", ".join(
        toml_string(value) for value in values
    ) + "]"


def normalize_tags(tags: Any) -> List[str]:
    if not isinstance(tags, list):
        raise ValueError("Article tags must be a list.")
    cleaned: List[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if tag and tag not in cleaned:
            cleaned.append(tag)
    if not cleaned:
        raise ValueError(
            "Article must contain at least one tag."
        )
    return cleaned


def save_post(post_path: Path, content: str) -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = post_path.with_suffix(".md.tmp")
    try:
        with temp_path.open(
            "w",
            encoding="utf-8",
            newline="\n",
        ) as file:
            file.write(content)
        temp_path.replace(post_path)
    except OSError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not write post file: {exc}"
        ) from exc


def find_column(
    fieldnames: List[str],
    target: str,
) -> Optional[str]:
    target_normalized = target.strip().lower()
    for field in fieldnames:
        if field.strip().lower() == target_normalized:
            return field
    return None


def update_keywords_csv(
    keyword: str,
    slug: str,
) -> None:
    if not KEYWORDS_PATH.exists():
        print(
            "Warning: keywords.csv was not found. "
            "Skipping keyword status update."
        )
        return

    try:
        with KEYWORDS_PATH.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames:
                raise ValueError(
                    "keywords.csv has no header row."
                )
            fieldnames = reader.fieldnames
            rows = list(reader)

        keyword_column = find_column(fieldnames, "Keyword")
        status_column = find_column(fieldnames, "Status")
        url_column = find_column(fieldnames, "URL")
        date_column = find_column(fieldnames, "Date")

        if keyword_column is None:
            raise ValueError(
                "keywords.csv must contain a 'Keyword' column."
            )
        if status_column is None:
            raise ValueError(
                "keywords.csv must contain a 'Status' column."
            )

        matched = False
        site_url = os.getenv("SITE_URL", "").strip().rstrip("/")
        relative_url = f"/posts/{slug}/"
        post_url = (
            f"{site_url}{relative_url}"
            if site_url
            else relative_url
        )
        current_date = datetime.now(
            timezone.utc
        ).date().isoformat()

        for row in rows:
            row_keyword = (
                row.get(keyword_column, "") or ""
            ).strip()
            if row_keyword.casefold() == keyword.casefold():
                row[status_column] = "published"
                if url_column is not None:
                    row[url_column] = post_url
                if date_column is not None:
                    row[date_column] = current_date
                matched = True
                break

        if not matched:
            raise ValueError(
                f"Keyword '{keyword}' was not found "
                "in keywords.csv."
            )

        temp_path = KEYWORDS_PATH.with_suffix(".csv.tmp")
        with temp_path.open(
            "w",
            encoding="utf-8",
            newline="",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            writer.writerows(rows)

        temp_path.replace(KEYWORDS_PATH)

        print(
            f"Keyword status updated to 'published': {keyword}"
        )

    except OSError as exc:
        raise RuntimeError(
            f"Could not update keywords.csv: {exc}"
        ) from exc


def main() -> int:
    print("=" * 70)
    print("Hugo publisher")
    print("=" * 70)

    try:
        article = load_article()

        keyword = str(article.get("keyword", "")).strip()
        title = str(article.get("title", "")).strip()
        slug = str(article.get("slug", "")).strip()
        description = str(
            article.get("meta_description", "")
        ).strip()
        content_markdown = str(
            article.get("content_markdown", "")
        ).strip()
        image = str(article.get("image", "")).strip()
        image_file = str(
            article.get("image_file", "")
        ).strip()

        tags = normalize_tags(article.get("tags", []))

        if not keyword:
            raise ValueError(
                "article.json is missing 'keyword'."
            )
        if not title:
            raise ValueError(
                "article.json is missing 'title'."
            )
        if not description:
            raise ValueError(
                "article.json is missing 'meta_description'."
            )
        if not content_markdown:
            raise ValueError(
                "article.json is missing 'content_markdown'."
            )

        slug = validate_slug(slug)

        expected_image_path = IMAGE_DIR / f"{slug}.jpg"

        if not expected_image_path.exists():
            raise FileNotFoundError(
                "Expected image was not found: "
                f"{expected_image_path}"
            )

        if expected_image_path.stat().st_size == 0:
            raise ValueError(
                f"Image file is empty: {expected_image_path}"
            )

        if not image:
            image = f"/images/{slug}.jpg"

        if not image_file:
            image_file = str(
                expected_image_path.relative_to(ROOT_DIR)
            )

        publication_date = datetime.now(timezone.utc)
        date_string = publication_date.isoformat()

        categories = [
            "Home Organization",
            "Small-Space Living",
        ]

        photographer = str(
            article.get("photographer", "")
        ).strip()
        photographer_url = str(
            article.get("photographer_url", "")
        ).strip()
        pexels_url = str(
            article.get("pexels_url", "")
        ).strip()

        attribution = ""

        if photographer:
            if photographer_url:
                attribution = (
                    "\n\n---\n\n"
                    "### Image Attribution\n\n"
                    f"Photo by "
                    f"[{photographer}]({photographer_url})"
                    " via Pexels."
                )
            else:
                attribution = (
                    "\n\n---\n\n"
                    "### Image Attribution\n\n"
                    f"Photo by {photographer} via Pexels."
                )
        elif pexels_url:
            attribution = (
                "\n\n---\n\n"
                "### Image Attribution\n\n"
                f"Photo via [Pexels]({pexels_url})."
            )

        frontmatter = (
            "+++\n"
            f"title = {toml_string(title)}\n"
            f"date = {toml_string(date_string)}\n"
            f"description = {toml_string(description)}\n"
            f"image = {toml_string(image)}\n"
            f"tags = {toml_array(tags)}\n"
            f"categories = {toml_array(categories)}\n"
            "draft = false\n"
            "+++\n"
        )

        post_content = (
            frontmatter
            + "\n"
            + content_markdown
            + attribution
            + "\n"
        )

        post_path = POSTS_DIR / f"{slug}.md"

        save_post(post_path, post_content)
        update_keywords_csv(keyword, slug)

        print("")
        print("=" * 70)
        print("POST PUBLISHED TO HUGO")
        print("=" * 70)
        print(f"Keyword: {keyword}")
        print(f"Title: {title}")
        print(f"Slug: {slug}")
        print(f"Post: {post_path}")
        print(f"Image: {expected_image_path}")
        print(f"Image URL: {image}")
        print(f"Categories: {', '.join(categories)}")
        print(f"Tags: {', '.join(tags)}")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print(
            "\nOperation cancelled by user.",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
