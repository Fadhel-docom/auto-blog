import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"
POSTS_DIR = ROOT_DIR / "content" / "posts"
IMAGE_DIR = ROOT_DIR / "static" / "images"
KEYWORDS_PATH = ROOT_DIR / "keywords.csv"


def load_article() -> dict[str, Any]:
    """Load and validate article.json."""
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(
            f"article.json not found: {ARTICLE_PATH}"
        )

    with ARTICLE_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        article = json.load(file)

    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain a JSON object."
        )

    return article


def validate_slug(slug: str) -> str:
    """Validate and normalize the article slug."""
    slug = str(slug).strip().lower()

    if not slug:
        raise ValueError("Article slug is empty.")

    if not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*",
        slug,
    ):
        raise ValueError(f"Invalid slug: {slug}")

    return slug


def toml_string(value: Any) -> str:
    """Convert a Python value to a TOML basic string."""
    value = str(value)
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\r", "\\r")
    value = value.replace("\n", "\\n")
    return f'"{value}"'


def toml_array(values: list[Any]) -> str:
    """Convert a list of values to a TOML string array."""
    return "[" + ", ".join(
        toml_string(value) for value in values
    ) + "]"


def normalize_tags(tags: Any) -> list[str]:
    """Normalize article tags."""
    if tags is None:
        return []

    if isinstance(tags, str):
        tags = [tags]

    if not isinstance(tags, list):
        raise ValueError("Article 'tags' must be a list.")

    normalized = []

    for tag in tags:
        tag = str(tag).strip()
        if tag:
            normalized.append(tag)

    return normalized


def save_post(
    post_path: Path,
    content: str,
) -> None:
    """Save the generated Hugo post."""
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    post_path.write_text(content, encoding="utf-8")


def find_column(
    fieldnames: list[str],
    candidates: list[str],
) -> str | None:
    """Find a CSV column using case-insensitive matching."""
    normalized = {
        field.strip().lower(): field
        for field in fieldnames
        if field
    }

    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]

    return None


def update_keywords_csv(
    keyword: str,
    slug: str,
) -> None:
    """Mark the published keyword in keywords.csv."""
    if not KEYWORDS_PATH.exists():
        print("keywords.csv not found; skipping keyword update.")
        return

    with KEYWORDS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            print("keywords.csv has no header; skipping.")
            return

        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    keyword_column = find_column(
        fieldnames,
        ["keyword", "keywords", "topic"],
    )
    status_column = find_column(fieldnames, ["status"])
    slug_column = find_column(fieldnames, ["slug"])
    published_at_column = find_column(
        fieldnames,
        ["published_at", "published date", "publication_date"],
    )

    if not keyword_column:
        print("No keyword column found; skipping.")
        return

    target_keyword = str(keyword).strip().lower()
    updated = False

    for row in rows:
        row_keyword = str(
            row.get(keyword_column, "")
        ).strip().lower()

        if row_keyword != target_keyword:
            continue

        if status_column:
            row[status_column] = "published"

        if slug_column:
            row[slug_column] = slug

        if published_at_column:
            row[published_at_column] = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            )

        updated = True
        break

    if not updated:
        print(f"Keyword not found in keywords.csv: {keyword}")
        return

    temp_path = KEYWORDS_PATH.with_suffix(".tmp.csv")

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
    print(f"Updated keywords.csv: {keyword}")


def normalize_images(
    article: dict[str, Any],
    slug: str,
) -> list[dict[str, Any]]:
    """Validate and normalize the five downloaded images."""
    images = article.get("images")

    if not isinstance(images, list):
        raise ValueError(
            "article.json must contain an 'images' array."
        )

    if len(images) != 5:
        raise ValueError("Exactly 5 images are required.")

    normalized = []

    for index, image in enumerate(images, start=1):
        if not isinstance(image, dict):
            raise ValueError(
                f"Image {index} must be an object."
            )

        expected_filename = f"{slug}-{index}.jpg"
        expected_path = IMAGE_DIR / expected_filename

        if not expected_path.exists():
            raise FileNotFoundError(
                f"Image {index} not found: {expected_path}"
            )

        if expected_path.stat().st_size <= 0:
            raise ValueError(
                f"Image {index} is empty: {expected_path}"
            )

        file_url = str(image.get("file", "")).strip()

        if not file_url:
            file_url = f"/images/{expected_filename}"

        normalized_image = dict(image)
        normalized_image["file"] = file_url
        normalized_image["file_path"] = (
            str(
                image.get(
                    "file_path",
                    f"static/images/{expected_filename}",
                )
            ).strip()
            or f"static/images/{expected_filename}"
        )

        normalized.append(normalized_image)

    return normalized


def main() -> int:
    """Publish article.json as a Hugo post."""
    try:
        article = load_article()

        keyword = str(article.get("keyword", "")).strip()
        if not keyword:
            raise ValueError(
                "article.json is missing 'keyword'."
            )

        title = str(article.get("title", "")).strip()
        if not title:
            raise ValueError(
                "article.json is missing 'title'."
            )

        slug = validate_slug(article.get("slug", ""))

        description = str(
            article.get("meta_description", "")
        ).strip()
        if not description:
            raise ValueError(
                "article.json is missing 'meta_description'."
            )

        content_markdown = str(
            article.get("content_markdown", "")
        ).strip()
        if not content_markdown:
            raise ValueError(
                "article.json is missing 'content_markdown'."
            )

        tags = normalize_tags(article.get("tags", []))
        images = normalize_images(article, slug)

        if len(images) != 5:
            raise ValueError(
                "Exactly 5 images are required before publishing."
            )

        image_urls = [image["file"] for image in images]
        first_image = image_urls[0]

        publication_date = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
        )

        categories = [
            "Home Organization",
            "Small-Space Living",
        ]

        # Add image credits to the end of the article.
        # Related Posts are NOT added here.
        # They are rendered by layouts/_default/single.html.
        image_attribution = []

        for index, image in enumerate(images, start=1):
            photographer = str(
                image.get("photographer", "")
            ).strip()
            photographer_url = str(
                image.get("photographer_url", "")
            ).strip()
            pexels_url = str(
                image.get("pexels_url", "")
            ).strip()

            if photographer:
                if photographer_url:
                    attribution = (
                        f"Photo {index}: "
                        f"[{photographer}]"
                        f"({photographer_url})"
                    )
                else:
                    attribution = (
                        f"Photo {index}: {photographer}"
                    )

                if pexels_url:
                    attribution += (
                        f" via [Pexels]({pexels_url})"
                    )

                image_attribution.append(attribution)

        if image_attribution:
            content_markdown += (
                "\n\n---\n\n"
                "### Image Credits\n\n"
                + "\n".join(
                    f"- {item}"
                    for item in image_attribution
                )
                + "\n"
            )

        frontmatter = (
            "+++\n"
            f"title = {toml_string(title)}\n"
            f"date = {toml_string(publication_date)}\n"
            f"description = {toml_string(description)}\n"
            f"image = {toml_string(first_image)}\n"
            f"images = {toml_array(image_urls)}\n"
            f"tags = {toml_array(tags)}\n"
            f"categories = {toml_array(categories)}\n"
            "draft = false\n"
            "+++\n"
        )

        post_content = (
            frontmatter
            + "\n"
            + content_markdown.strip()
            + "\n"
        )

        post_path = POSTS_DIR / f"{slug}.md"

        save_post(post_path, post_content)
        update_keywords_csv(keyword, slug)

        print("")
        print("=" * 70)
        print("Article published successfully.")
        print("=" * 70)
        print(f"Keyword: {keyword}")
        print(f"Title: {title}")
        print(f"Slug: {slug}")
        print(f"Post: {post_path}")
        print(f"Images: {len(image_urls)}")

        for index, image_url in enumerate(
            image_urls, start=1
        ):
            print(f"  {index}. {image_url}")

        print("Related Posts: rendered by single.html")
        print("Keyword status: published")

        return 0

    except KeyboardInterrupt:
        print(
            "\nOperation cancelled.",
            file=sys.stderr,
        )
        return 130

    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
