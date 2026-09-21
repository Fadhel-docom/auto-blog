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
            f"article.json was not found: {ARTICLE_PATH}"
        )

    with ARTICLE_PATH.open("r", encoding="utf-8") as file:
        article = json.load(file)

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

    cleaned = []

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

    with temp_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        file.write(content)

    temp_path.replace(post_path)


def find_column(
    fieldnames: List[str],
    target: str,
) -> Optional[str]:
    target = target.strip().lower()

    for field in fieldnames:
        if field.strip().lower() == target:
            return field

    return None


def update_keywords_csv(keyword: str, slug: str) -> None:
    if not KEYWORDS_PATH.exists():
        return

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

    if not keyword_column or not status_column:
        raise ValueError(
            "keywords.csv must contain Keyword and Status columns."
        )

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

    matched = False

    for row in rows:
        row_keyword = str(
            row.get(keyword_column, "")
        ).strip()

        if row_keyword.casefold() == keyword.casefold():
            row[status_column] = "published"

            if url_column:
                row[url_column] = post_url

            if date_column:
                row[date_column] = current_date

            matched = True
            break

    if not matched:
        raise ValueError(
            f"Keyword '{keyword}' was not found in keywords.csv."
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


def get_post_date(path: Path) -> datetime:
    try:
        text = path.read_text(encoding="utf-8")

        match = re.search(
            r"(?m)^date\s*=\s*[\"']([^\"']+)",
            text,
        )

        if match:
            value = match.group(1)

            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )
            except ValueError:
                pass

    except OSError:
        pass

    return datetime.fromtimestamp(
        path.stat().st_mtime,
        tz=timezone.utc,
    )


def get_related_posts(current_slug: str) -> List[Dict[str, str]]:
    if not POSTS_DIR.exists():
        return []

    posts = []

    for path in POSTS_DIR.glob("*.md"):
        if path.stem == current_slug:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        title_match = re.search(
            r"(?m)^title\s*=\s*[\"'](.+?)[\"']\s*$",
            text,
        )

        if not title_match:
            title_match = re.search(
                r"(?m)^title:\s*[\"']?(.+?)[\"']?\s*$",
                text,
            )

        title = (
            title_match.group(1).strip()
            if title_match
            else path.stem.replace("-", " ").title()
        )

        posts.append(
            {
                "title": title,
                "slug": path.stem,
                "date": get_post_date(path),
            }
        )

    posts.sort(
        key=lambda item: item["date"],
        reverse=True,
    )

    return posts[:3]


def build_related_posts_markdown(current_slug: str) -> str:
    related = get_related_posts(current_slug)

    if not related:
        return ""

    lines = [
        "",
        "",
        "## Related Posts",
        "",
    ]

    for post in related:
        lines.append(
            f"- [{post['title']}]"
            f"(/posts/{post['slug']}/)"
        )

    return "\n".join(lines)


def normalize_images(
    article: Dict[str, Any],
    slug: str,
) -> List[Dict[str, Any]]:
    raw_images = article.get("images")

    if not isinstance(raw_images, list):
        raise ValueError(
            "article.json must contain an 'images' array."
        )

    if len(raw_images) != 5:
        raise ValueError(
            "article.json must contain exactly 5 images."
        )

    images = []

    for index, item in enumerate(raw_images, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Image {index} is invalid.")

        image_url = str(item.get("file", "")).strip()

        if not image_url:
            image_url = f"/images/{slug}-{index}.jpg"

        expected_path = IMAGE_DIR / f"{slug}-{index}.jpg"

        if not expected_path.exists():
            raise FileNotFoundError(
                f"Missing image {index}: {expected_path}"
            )

        if expected_path.stat().st_size == 0:
            raise ValueError(
                f"Image {index} is empty: {expected_path}"
            )

        images.append({**item, "file": image_url})

    return images


def main() -> int:
    try:
        print("=" * 70)
        print("Hugo publisher")
        print("=" * 70)

        article = load_article()

        keyword = str(article.get("keyword", "")).strip()
        title = str(article.get("title", "")).strip()
        slug = validate_slug(str(article.get("slug", "")))
        description = str(
            article.get("meta_description", "")
        ).strip()
        content_markdown = str(
            article.get("content_markdown", "")
        ).strip()

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

        tags = normalize_tags(article.get("tags", []))
        images = normalize_images(article, slug)

        if len(images) != 5:
            raise ValueError(
                "Exactly 5 images are required before publishing."
            )

        image_urls = [image["file"] for image in images]
        first_image = image_urls[0]

        related_markdown = build_related_posts_markdown(slug)

        if related_markdown:
            content_markdown = (
                content_markdown.rstrip() + related_markdown
            )

        publication_date = datetime.now(
            timezone.utc
        ).isoformat()

        categories = [
            "Home Organization",
            "Small-Space Living",
        ]

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
            image_urls,
            start=1,
        ):
            print(f"  {index}. {image_url}")

        related_count = len(get_related_posts(slug))
        print(f"Related posts: {related_count}")
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
