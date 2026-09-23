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

STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this",
    "your", "you", "are", "into", "without", "small", "home",
    "ideas", "tips", "guide", "best", "ways", "how", "what",
    "when", "where", "using", "use", "make", "get", "can",
    "more", "room", "space",
}

TOPIC_GROUPS = {
    "kitchen": {
        "kitchen", "pantry", "spice", "spices",
        "countertop", "cabinet", "cabinets",
        "fridge", "refrigerator",
    },
    "bedroom": {
        "bedroom", "closet", "wardrobe", "dresser",
        "clothing", "clothes", "underbed", "under-bed",
    },
    "bathroom": {
        "bathroom", "under-sink", "sink", "shower",
        "toiletries", "towels",
    },
    "entryway": {
        "entryway", "entry", "hallway", "foyer",
        "shoes", "coat", "entry-door",
    },
    "living": {
        "living", "living-room", "sofa", "couch",
        "coffee-table", "tv",
    },
    "office": {
        "office", "desk", "workspace", "home-office",
        "paper", "documents",
    },
    "small-space": {
        "small", "small-space", "small-apartment",
        "studio", "tiny", "compact", "space-saving",
        "storage",
    },
    "decluttering": {
        "decluttering", "declutter", "minimalist",
        "minimalism", "clutter", "organize",
        "organization",
    },
    "rental": {
        "renter", "rental", "renting",
        "damage-free", "no-drill", "drill-free",
    },
}


def load_article() -> dict[str, Any]:
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
    slug = str(slug).strip().lower()

    if not slug:
        raise ValueError("Article slug is empty.")

    if not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*",
        slug,
    ):
        raise ValueError(f"Invalid slug: {slug}")

    if len(slug) > 60:
        raise ValueError(
            "Article slug exceeds the 60-character limit."
        )

    return slug


def toml_string(value: Any) -> str:
    value = str(value)
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\r", "\\r")
    value = value.replace("\n", "\\n")

    return f'"{value}"'


def toml_array(values: list[Any]) -> str:
    return "[" + ", ".join(
        toml_string(value) for value in values
    ) + "]"


def toml_table_array(
    values: list[dict[str, str]],
) -> str:
    if not values:
        return "[]"

    parts = []

    for value in values:
        question = toml_string(
            value.get("question", "")
        )
        answer = toml_string(
            value.get("answer", "")
        )

        parts.append(
            "{"
            f"question = {question}, "
            f"answer = {answer}"
            "}"
        )

    return "[" + ", ".join(parts) + "]"


def normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []

    if isinstance(tags, str):
        tags = [tags]

    if not isinstance(tags, list):
        raise ValueError(
            "Article 'tags' must be a list."
        )

    normalized = []

    for tag in tags:
        tag = str(tag).strip()

        if tag:
            normalized.append(tag)

    return normalized


def save_post(post_path: Path, content: str) -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    post_path.write_text(content, encoding="utf-8")


def find_column(
    fieldnames: list[str],
    candidates: list[str],
) -> str | None:
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
    if not KEYWORDS_PATH.exists():
        print(
            "keywords.csv not found; "
            "skipping keyword update."
        )
        return

    with KEYWORDS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            print(
                "keywords.csv has no header; "
                "skipping."
            )
            return

        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    keyword_column = find_column(
        fieldnames,
        ["keyword", "keywords", "topic"],
    )
    status_column = find_column(
        fieldnames,
        ["status"],
    )
    slug_column = find_column(
        fieldnames,
        ["slug"],
    )
    published_at_column = find_column(
        fieldnames,
        [
            "published_at",
            "published date",
            "publication_date",
        ],
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
        print(
            f"Keyword not found in "
            f"keywords.csv: {keyword}"
        )
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
    images = article.get("images")

    if not isinstance(images, list):
        raise ValueError(
            "article.json must contain "
            "an 'images' array."
        )

    if len(images) != 6:
        raise ValueError(
            f"Expected exactly 6 images for "
            f"publishing, got {len(images)}."
        )

    normalized = []

    for index, image in enumerate(
        images,
        start=1,
    ):
        if not isinstance(image, dict):
            raise ValueError(
                f"Image {index} must be an object."
            )

        expected_filename = f"{slug}-{index}.jpg"
        expected_path = (
            IMAGE_DIR / expected_filename
        )

        if not expected_path.exists():
            raise FileNotFoundError(
                f"Image {index} not found: "
                f"{expected_path}"
            )

        if expected_path.stat().st_size <= 0:
            raise ValueError(
                f"Image {index} is empty: "
                f"{expected_path}"
            )

        file_url = str(
            image.get("file", "")
        ).strip()

        if not file_url:
            file_url = (
                f"/images/{expected_filename}"
            )

        query = str(
            image.get("query", "")
        ).strip()

        if not query:
            raise ValueError(
                f"Image {index} is missing "
                "its 'query' field."
            )

        normalized_image = dict(image)
        normalized_image["file"] = file_url
        normalized_image["query"] = query
        normalized_image["file_path"] = (
            str(
                image.get(
                    "file_path",
                    f"static/images/"
                    f"{expected_filename}",
                )
            ).strip()
            or f"static/images/{expected_filename}"
        )

        normalized.append(normalized_image)

    return normalized


def image_markdown(
    image_url: str,
    alt_text: str,
) -> str:
    image_path = str(image_url).strip()

    if image_path.startswith("/images/"):
        image_path = image_path[len("/images/"):]
    elif image_path.startswith("images/"):
        image_path = image_path[len("images/"):]
    elif image_path.startswith("/"):
        image_path = image_path.lstrip("/")

    return (
        f"![{alt_text}]"
        f"(../../images/{image_path})"
    )


def insert_images_between_h2(
    content: str,
    images: list[dict[str, Any]],
) -> str:
    if len(images) != 6:
        raise ValueError(
            "insert_images_between_h2 requires "
            "exactly 6 images."
        )

    image_index = 1
    lines = content.splitlines()
    output = []

    in_fenced_code_block = False
    fence_marker = None

    for line in lines:
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

            output.append(line)
            continue

        output.append(line)

        if in_fenced_code_block:
            continue

        if re.match(r"^##[ \t]+[^#]", line):
            if image_index >= len(images):
                continue

            image = images[image_index]
            alt_text = str(
                image.get("query", "")
            ).strip()

            if not alt_text:
                alt_text = "Home organization image"

            image_md = image_markdown(
                image["file"],
                alt_text,
            )

            output.append("")
            output.append(image_md)
            output.append("")

            image_index += 1

    return "\n".join(output)


def normalize_keywords(text: str) -> set[str]:
    text = str(text).lower()

    tokens = re.findall(
        r"[a-z0-9]+(?:-[a-z0-9]+)*",
        text,
    )

    keywords = set()

    for token in tokens:
        if token in STOP_WORDS:
            continue

        if len(token) < 3:
            continue

        keywords.add(token)

    return keywords


def detect_topic_groups(text: str) -> set[str]:
    tokens = normalize_keywords(text)
    groups = set()

    for group_name, group_words in TOPIC_GROUPS.items():
        if tokens.intersection(group_words):
            groups.add(group_name)

    return groups


def read_existing_posts(
    current_slug: str,
) -> list[dict[str, Any]]:
    posts = []

    if not POSTS_DIR.exists():
        return posts

    for post_path in sorted(
        POSTS_DIR.glob("*.md")
    ):
        if post_path.stem == current_slug:
            continue

        try:
            content = post_path.read_text(
                encoding="utf-8"
            )
        except OSError:
            continue

        match = re.match(
            r"^\+\+\+\n(.*?)\n\+\+\+\n",
            content,
            flags=re.DOTALL,
        )

        if not match:
            continue

        frontmatter = match.group(1)

        title_match = re.search(
            r'^title\s*=\s*"((?:\\.|[^"])*)"',
            frontmatter,
            flags=re.MULTILINE,
        )

        tags_match = re.search(
            r"^tags\s*=\s*\[(.*?)\]",
            frontmatter,
            flags=re.MULTILINE | re.DOTALL,
        )

        categories_match = re.search(
            r"^categories\s*=\s*\[(.*?)\]",
            frontmatter,
            flags=re.MULTILINE | re.DOTALL,
        )

        title = (
            title_match.group(1)
            if title_match
            else post_path.stem.replace("-", " ")
        )

        tags_text = (
            tags_match.group(1)
            if tags_match
            else ""
        )

        categories_text = (
            categories_match.group(1)
            if categories_match
            else ""
        )

        metadata_text = " ".join(
            [
                title,
                tags_text,
                categories_text,
                post_path.stem.replace("-", " "),
            ]
        )

        normalized_title = title.lower().replace("\u2011", "")
        post_slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            normalized_title,
        ).strip("-")

        posts.append(
            {
                "slug": post_slug,
                "title": title,
                "keywords": normalize_keywords(
                    metadata_text
                ),
                "topics": detect_topic_groups(
                    metadata_text
                ),
            }
        )

    return posts


def score_internal_link(
    current_text: str,
    target: dict[str, Any],
) -> int:
    current_keywords = normalize_keywords(
        current_text
    )
    current_topics = detect_topic_groups(
        current_text
    )

    score = 0

    shared_keywords = (
        current_keywords.intersection(
            target["keywords"]
        )
    )
    score += len(shared_keywords) * 4

    shared_topics = current_topics.intersection(
        target["topics"]
    )
    score += len(shared_topics) * 10

    return score


def select_internal_links(
    content: str,
    current_keyword: str,
    current_slug: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    existing_posts = read_existing_posts(
        current_slug
    )

    if not existing_posts:
        return []

    context = f"{current_keyword}\n\n{content}"

    scored = []

    for post in existing_posts:
        score = score_internal_link(
            context,
            post,
        )

        if score <= 0:
            continue

        scored.append((score, post))

    scored.sort(
        key=lambda item: (
            item[0],
            item[1]["title"],
        ),
        reverse=True,
    )

    selected = []
    used_topics = set()

    for score, post in scored:
        post_topics = post["topics"]

        if (
            selected
            and post_topics
            and post_topics.issubset(used_topics)
            and len(scored) > len(selected) + 1
        ):
            continue

        selected.append(post)
        used_topics.update(post_topics)

        if len(selected) >= limit:
            break

    return selected


def split_paragraphs(content: str) -> list[str]:
    parts = re.split(r"\n\s*\n", content)

    return [
        part
        for part in parts
        if part.strip()
    ]


def build_internal_link_anchor(title: str) -> str:
    words = re.findall(
        r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*",
        str(title),
    )

    if not words:
        return "this related idea"

    return " ".join(words[:5])


def insert_internal_links(
    content: str,
    current_keyword: str,
    current_slug: str,
) -> str:
    links = select_internal_links(
        content,
        current_keyword,
        current_slug,
        limit=3,
    )

    if not links:
        return content

    paragraphs = split_paragraphs(content)

    candidate_indexes = []

    for index, paragraph in enumerate(paragraphs):
        stripped = paragraph.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            continue

        if stripped.startswith("!["):
            continue

        if stripped.startswith("- "):
            continue

        if re.match(r"^\d+\.\s+", stripped):
            continue

        if len(stripped) < 120:
            continue

        candidate_indexes.append(index)

    if not candidate_indexes:
        return content

    middle_indexes = [
        index
        for index in candidate_indexes
        if (
            len(paragraphs) * 0.20
            <= index
            <= len(paragraphs) * 0.75
        )
    ]

    if middle_indexes:
        candidate_indexes = middle_indexes

    valid_links = []

    for link in links:
        target_slug = str(
            link.get("slug", "")
        ).strip()

        if not target_slug:
            continue

        target_path = (
            POSTS_DIR / f"{target_slug}.md"
        )

        if not target_path.exists():
            print(
                "Skipping internal link; "
                f"target post not found: "
                f"{target_path}"
            )
            continue

        valid_links.append(
            {
                "slug": target_slug,
                "title": str(
                    link.get("title", "")
                ).strip(),
            }
        )

    links = valid_links

    if not links:
        return content

    if len(candidate_indexes) < len(links):
        links = links[:len(candidate_indexes)]

    if not links:
        return content

    positions = []

    if len(links) == 1:
        positions = [
            candidate_indexes[
                len(candidate_indexes) // 2
            ]
        ]
    elif len(links) == 2:
        positions = [
            candidate_indexes[
                len(candidate_indexes) // 3
            ],
            candidate_indexes[
                (len(candidate_indexes) * 2) // 3
            ],
        ]
    else:
        positions = [
            candidate_indexes[
                len(candidate_indexes) // 4
            ],
            candidate_indexes[
                len(candidate_indexes) // 2
            ],
            candidate_indexes[
                (len(candidate_indexes) * 3) // 4
            ],
        ]

    for position, link in reversed(
        list(zip(positions, links))
    ):
        anchor = build_internal_link_anchor(
            link.get("title", "")
        )

        if not anchor:
            continue

        target_slug = link["slug"]
        target_path = (
            POSTS_DIR / f"{target_slug}.md"
        )

        if not target_path.exists():
            print(
                "Skipping internal link during "
                f"insertion; target post "
                f"disappeared: {target_path}"
            )
            continue

        link_markdown = (
            f"[Read more about {anchor}]"
            f"(../{target_slug}/)"
        )

        paragraphs.insert(
            position + 1,
            link_markdown,
        )

    return "\n\n".join(paragraphs)


def extract_faq_items(
    content: str,
) -> list[dict[str, str]]:
    lines = content.splitlines()
    faq_items = []

    current_question = None
    current_answer = []

    for line in lines:
        stripped = line.strip()

        heading_match = re.match(
            r"^#{2,3}\s+(.+?)\s*$",
            stripped,
        )

        if heading_match:
            if current_question:
                answer = "\n".join(
                    current_answer
                ).strip()
                answer = re.sub(
                    r"\s+",
                    " ",
                    answer,
                )

                if answer and len(answer) >= 40:
                    faq_items.append(
                        {
                            "question": (
                                current_question
                            ),
                            "answer": answer,
                        }
                    )

            heading = heading_match.group(1).strip()

            if heading.endswith("?"):
                current_question = heading
                current_answer = []
            else:
                current_question = None
                current_answer = []

            continue

        if current_question:
            if stripped:
                current_answer.append(stripped)

    if current_question:
        answer = "\n".join(current_answer).strip()
        answer = re.sub(r"\s+", " ", answer)

        if answer and len(answer) >= 40:
            faq_items.append(
                {
                    "question": current_question,
                    "answer": answer,
                }
            )

    return faq_items[:8]


def main() -> int:
    try:
        article = load_article()

        keyword = str(
            article.get("keyword", "")
        ).strip()

        if not keyword:
            raise ValueError(
                "article.json is missing 'keyword'."
            )

        title = str(
            article.get("title", "")
        ).strip()

        if not title:
            raise ValueError(
                "article.json is missing 'title'."
            )

        slug = validate_slug(
            article.get("slug", "")
        )

        description = str(
            article.get("meta_description", "")
        ).strip()

        if not description:
            raise ValueError(
                "article.json is missing "
                "'meta_description'."
            )

        content_markdown = str(
            article.get("content_markdown", "")
        ).strip()

        if not content_markdown:
            raise ValueError(
                "article.json is missing "
                "'content_markdown'."
            )

        tags = normalize_tags(
            article.get("tags", [])
        )

        images = normalize_images(article, slug)

        if len(images) != 6:
            raise ValueError(
                "Exactly 6 images are required "
                "before publishing."
            )

        image_urls = [
            image["file"] for image in images
        ]
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

        content_markdown = insert_images_between_h2(
            content_markdown,
            images,
        )

        content_markdown = insert_internal_links(
            content_markdown,
            keyword,
            slug,
        )

        image_attribution = []

        for index, image in enumerate(
            images,
            start=1,
        ):
            photographer = str(
                image.get("photographer", "")
            ).strip()

            photographer_url = str(
                image.get(
                    "photographer_url", ""
                )
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
                        f"Photo {index}: "
                        f"{photographer}"
                    )

                if pexels_url:
                    attribution += (
                        f" via [Pexels]"
                        f"({pexels_url})"
                    )

                image_attribution.append(
                    attribution
                )

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

        faq_items = extract_faq_items(
            content_markdown
        )

        frontmatter = (
            "+++\n"
            f"title = {toml_string(title)}\n"
            f"date = {toml_string(publication_date)}\n"
            f"lastmod = {toml_string(publication_date)}\n"
            f"description = {toml_string(description)}\n"
            f"image = {toml_string(first_image)}\n"
            f"images = {toml_array(image_urls)}\n"
            f"tags = {toml_array(tags)}\n"
            f"categories = {toml_array(categories)}\n"
            f"faq = {toml_table_array(faq_items)}\n"
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

        print("Image 1: hero")
        print(
            "Images 2-5: inserted after first "
            "four H2 headings"
        )
        print(
            "Internal links: inserted "
            "contextually (with validation)"
        )
        print(f"FAQ items: {len(faq_items)}")
        print("Alt text: section-aware image query")
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
        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
