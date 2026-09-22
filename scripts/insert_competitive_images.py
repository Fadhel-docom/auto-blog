#!/usr/bin/env python3

import json
import re
import sys

from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]

ARTICLE_PATH = ROOT_DIR / "article.json"
POSTS_DIR = ROOT_DIR / "content" / "posts"
IMAGE_DIR = ROOT_DIR / "static" / "images"

REQUIRED_IMAGES = 10
EXISTING_PUBLISHED_IMAGES = 5
ADDITIONAL_IMAGES = 5
MARKDOWN_EXISTING_IMAGES = 4


def load_article() -> Dict[str, Any]:
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(
            f"article.json was not found at: "
            f"{ARTICLE_PATH}"
        )

    try:
        with ARTICLE_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            article = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"article.json contains invalid JSON: "
            f"{exc}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Could not read article.json: {exc}"
        ) from exc

    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain a JSON object."
        )

    return article


def get_required_string(
    article: Dict[str, Any],
    field_name: str,
) -> str:
    value = article.get(field_name, "")

    if not isinstance(value, str):
        raise ValueError(
            f"article.json field '{field_name}' "
            "must be a string."
        )

    value = value.strip()

    if not value:
        raise ValueError(
            f"article.json field '{field_name}' "
            "is empty."
        )

    return value


def get_post_path(slug: str) -> Path:
    return POSTS_DIR / f"{slug}.md"


def load_post(post_path: Path) -> str:
    if not post_path.exists():
        raise FileNotFoundError(
            f"Published post was not found: "
            f"{post_path}"
        )

    try:
        content = post_path.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise RuntimeError(
            f"Could not read published post: "
            f"{exc}"
        ) from exc

    if not content.strip():
        raise ValueError(
            f"Published post is empty: {post_path}"
        )

    return content


def save_post(
    post_path: Path,
    content: str,
) -> None:
    temp_path = post_path.with_suffix(
        ".md.competitive.tmp"
    )

    try:
        temp_path.write_text(
            content,
            encoding="utf-8",
        )

        temp_path.replace(post_path)

    except OSError as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        raise RuntimeError(
            f"Could not save published post: {exc}"
        ) from exc


def normalize_image_path(file_value: Any) -> str:
    value = str(file_value or "").strip()

    while (
        value.startswith("../")
        or value.startswith("./")
        or value.startswith("/")
    ):
        if value.startswith("../"):
            value = value[3:]
        elif value.startswith("./"):
            value = value[2:]
        else:
            value = value[1:]

    if value.startswith("images/"):
        value = value[len("images/"):]

    return value.strip()


def extract_image_paths(content: str) -> List[str]:
    matches = re.findall(
        r"!\[[^\]]*\]\(([^)\s]+)",
        content,
    )

    result = []

    for item in matches:
        normalized = normalize_image_path(item)

        if normalized:
            result.append(normalized)

    return result


def extract_frontmatter(content: str) -> str:
    toml_match = re.match(
        r"^\+\+\+\s*\n(.*?)\n\+\+\+\s*(?:\n|$)",
        content,
        flags=re.DOTALL,
    )

    if toml_match:
        return toml_match.group(1)

    yaml_match = re.match(
        r"^---\s*\n(.*?)\n---\s*(?:\n|$)",
        content,
        flags=re.DOTALL,
    )

    if yaml_match:
        return yaml_match.group(1)

    return ""


def extract_hero_image_path(
    content: str,
) -> Optional[str]:
    frontmatter = extract_frontmatter(content)

    if not frontmatter:
        return None

    toml_match = re.search(
        r'^\s*image\s*=\s*["\']((?:\\.|[^"\'])*)["\']\s*$',
        frontmatter,
        flags=re.MULTILINE,
    )

    if toml_match:
        value = toml_match.group(1).strip()

        if value:
            return normalize_image_path(value)

    yaml_quoted = re.search(
        r'^\s*image\s*:\s*["\']([^"\']*)["\']\s*(?:#.*)?$',
        frontmatter,
        flags=re.MULTILINE,
    )

    if yaml_quoted:
        value = yaml_quoted.group(1).strip()

        if value:
            return normalize_image_path(value)

    yaml_unquoted = re.search(
        r'^\s*image\s*:\s*([^\s#]+)\s*(?:#.*)?$',
        frontmatter,
        flags=re.MULTILINE,
    )

    if yaml_unquoted:
        value = yaml_unquoted.group(1).strip()

        if value:
            return normalize_image_path(value)

    return None


def get_existing_image_paths(content: str) -> set:
    paths = set(extract_image_paths(content))

    hero = extract_hero_image_path(content)

    if hero:
        paths.add(hero)

    return paths


def count_article_images(content: str) -> int:
    return len(get_existing_image_paths(content))


def build_markdown_image(image: Dict[str, Any]) -> str:
    filename = normalize_image_path(
        image.get("file", "")
    )

    if not filename:
        raise ValueError(
            "Image has an empty file path."
        )

    alt_text = str(
        image.get("query", "") or ""
    ).strip()

    if not alt_text:
        alt_text = "Home organization image"

    # NOTE:
    # Post is at content/posts/<slug>.md → rendered
    # at /auto-blog/posts/<slug>/.
    # ../../images/file.jpg → /auto-blog/images/file.jpg
    # Correct for GitHub Pages subpath deployment.
    return (
        f"![{alt_text}]"
        f"(../../images/{filename})"
    )


def validate_images(
    article: Dict[str, Any],
) -> List[Dict[str, Any]]:
    images = article.get("images")

    if not isinstance(images, list):
        raise ValueError(
            "article.json must contain an images list."
        )

    if len(images) != REQUIRED_IMAGES:
        raise ValueError(
            f"Expected exactly {REQUIRED_IMAGES} "
            f"images in article.json, got "
            f"{len(images)}."
        )

    slug = get_required_string(article, "slug")
    validated = []

    for index, image in enumerate(
        images,
        start=1,
    ):
        if not isinstance(image, dict):
            raise ValueError(
                f"Image #{index} must be an object."
            )

        filename = normalize_image_path(
            image.get("file", "")
        )

        expected_filename = f"{slug}-{index}.jpg"

        if filename != expected_filename:
            raise ValueError(
                f"Image #{index} filename mismatch. "
                f"Expected '{expected_filename}', "
                f"got '{filename}'."
            )

        image_path = IMAGE_DIR / expected_filename

        if not image_path.exists():
            raise FileNotFoundError(
                f"Image #{index} is missing from "
                f"disk: {image_path}"
            )

        if image_path.stat().st_size <= 0:
            raise ValueError(
                f"Image #{index} is empty: "
                f"{image_path}"
            )

        query = str(
            image.get("query", "") or ""
        ).strip()

        if not query:
            raise ValueError(
                f"Image #{index} has no "
                "query/alt text."
            )

        validated.append(image)

    return validated


def is_h2_line(line: str) -> bool:
    return bool(
        re.match(
            r"^\s*##[ \t]+[^#].*$",
            line,
        )
    )


def insert_additional_images(
    content: str,
    images: List[Dict[str, Any]],
) -> tuple:
    additional_images = images[
        EXISTING_PUBLISHED_IMAGES:
    ]

    if len(additional_images) != ADDITIONAL_IMAGES:
        raise ValueError(
            "Could not obtain exactly five "
            "additional images."
        )

    existing_paths = get_existing_image_paths(
        content
    )

    lines = content.splitlines()
    output: List[str] = []

    in_fenced_code_block = False
    fence_marker: Optional[str] = None

    h2_count = 0
    inserted = 0
    processed_targets = 0
    inserted_h2_numbers: List[int] = []

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

        if not is_h2_line(line):
            continue

        h2_count += 1

        if h2_count <= EXISTING_PUBLISHED_IMAGES:
            continue

        target_index = (
            h2_count
            - EXISTING_PUBLISHED_IMAGES
            - 1
        )

        if target_index >= len(additional_images):
            continue

        processed_targets += 1

        image = additional_images[target_index]

        image_number = (
            EXISTING_PUBLISHED_IMAGES
            + target_index
            + 1
        )

        filename = normalize_image_path(
            image.get("file", "")
        )

        if not filename:
            raise ValueError(
                f"Image {image_number} "
                "has an empty filename."
            )

        if filename in existing_paths:
            print(
                f"Image {image_number} already "
                "exists in the post; "
                "skipping duplicate."
            )

            inserted_h2_numbers.append(h2_count)
            continue

        output.append("")
        output.append(build_markdown_image(image))
        output.append("")

        inserted += 1
        inserted_h2_numbers.append(h2_count)
        existing_paths.add(filename)

        print(
            f"Inserted image {image_number} "
            f"after H2 #{h2_count}."
        )

    if processed_targets < ADDITIONAL_IMAGES:
        print(
            "WARNING: only "
            f"{processed_targets}/"
            f"{ADDITIONAL_IMAGES} target "
            "positions found."
        )

    return (
        "\n".join(output),
        inserted,
        inserted_h2_numbers,
    )


def remove_existing_image_credits(content: str) -> str:
    patterns = [
        r"\n{2,}---\s*\n+"
        r"#{2,3}[ \t]+Image Credits[ \t]*\n"
        r".*$",

        r"\n{2,}"
        r"#{2,3}[ \t]+Image Credits[ \t]*\n"
        r".*$",
    ]

    cleaned = content

    for pattern in patterns:
        cleaned = re.sub(
            pattern,
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )

    return cleaned.rstrip()


def build_credit_line(
    index: int,
    image: Dict[str, Any],
) -> str:
    photographer = str(
        image.get("photographer", "") or ""
    ).strip()

    photographer_url = str(
        image.get("photographer_url", "") or ""
    ).strip()

    pexels_url = str(
        image.get("pexels_url", "") or ""
    ).strip()

    if photographer:
        if photographer_url:
            photographer_text = (
                f"[{photographer}]"
                f"({photographer_url})"
            )
        else:
            photographer_text = photographer
    else:
        photographer_text = "Pexels photographer"

    if pexels_url:
        return (
            f"Photo {index}: "
            f"{photographer_text} "
            f"via [Pexels]({pexels_url})"
        )

    return (
        f"Photo {index}: "
        f"{photographer_text} via Pexels"
    )


def build_all_image_credits(
    images: List[Dict[str, Any]],
) -> str:
    lines = [
        "---",
        "",
        "## Image Credits",
        "",
    ]

    for index, image in enumerate(
        images,
        start=1,
    ):
        lines.append(
            "- " + build_credit_line(index, image)
        )

    lines.append("")

    return "\n".join(lines)


def update_image_credits(
    content: str,
    images: List[Dict[str, Any]],
) -> str:
    cleaned = remove_existing_image_credits(content)
    credits = build_all_image_credits(images)

    return cleaned.rstrip() + "\n\n" + credits


def verify_image_delta(
    before_count: int,
    after_count: int,
    inserted_count: int,
) -> None:
    expected = before_count + inserted_count

    if after_count != expected:
        raise RuntimeError(
            "Image count verification failed: "
            f"before={before_count}, "
            f"inserted={inserted_count}, "
            f"after={after_count}, "
            f"expected={expected}."
        )


def verify_expected_images(
    content: str,
    images: List[Dict[str, Any]],
) -> None:
    existing = get_existing_image_paths(content)
    missing = []

    for index, image in enumerate(
        images,
        start=1,
    ):
        filename = normalize_image_path(
            image.get("file", "")
        )

        if filename not in existing:
            missing.append(index)

    if missing:
        raise RuntimeError(
            "The post is missing image(s): "
            + ", ".join(str(i) for i in missing)
        )


def verify_credits(
    content: str,
    images: List[Dict[str, Any]],
) -> None:
    if "## Image Credits" not in content:
        raise RuntimeError(
            "Image Credits section is missing."
        )

    for index in range(1, len(images) + 1):
        marker = f"Photo {index}:"

        if marker not in content:
            raise RuntimeError(
                f"Credit for image {index} "
                "is missing."
            )


def print_image_state(
    label: str,
    content: str,
) -> None:
    paths = sorted(get_existing_image_paths(content))

    print("")
    print(f"{label} image state:")
    print(f"  Total images: {len(paths)}")

    for index, path in enumerate(
        paths,
        start=1,
    ):
        print(f"  {index}. {path}")

    print("")


def main() -> int:
    print("=" * 70)
    print("INSERT COMPETITIVE IMAGES")
    print("=" * 70)

    try:
        article = load_article()
        slug = get_required_string(article, "slug")
        images = validate_images(article)
        post_path = get_post_path(slug)
        content = load_post(post_path)

        before_count = count_article_images(content)

        print(f"Post: {post_path}")
        print(
            f"Images before insertion: "
            f"{before_count}"
        )
        print(
            f"Images in article.json: "
            f"{len(images)}"
        )

        print_image_state("Before", content)

        if before_count < MARKDOWN_EXISTING_IMAGES:
            raise RuntimeError(
                "Published post contains fewer "
                "than four Markdown images. "
                "The base publisher output is "
                "invalid."
            )

        if before_count >= REQUIRED_IMAGES:
            print(
                "Post already contains 10 or "
                "more images."
            )

            new_content = update_image_credits(
                content,
                images,
            )

            save_post(post_path, new_content)

            final_content = load_post(post_path)

            verify_expected_images(
                final_content,
                images,
            )
            verify_credits(final_content, images)

            print(
                "Credits normalized to all "
                "10 images."
            )

            print("=" * 70)
            print(
                "INSERT COMPETITIVE IMAGES COMPLETE"
            )
            print("=" * 70)

            return 0

        print(
            "Adding competitive images 6-10 "
            "after H2 #6-10."
        )

        new_content, inserted, h2_numbers = (
            insert_additional_images(
                content,
                images,
            )
        )

        after_count = count_article_images(new_content)

        print("")
        print(
            f"Images before insertion: "
            f"{before_count}"
        )
        print(f"Newly inserted images: {inserted}")
        print(
            f"Images after insertion: "
            f"{after_count}"
        )

        verify_image_delta(
            before_count,
            after_count,
            inserted,
        )
        verify_expected_images(new_content, images)

        print("Pre-save verification passed.")

        new_content = update_image_credits(
            new_content,
            images,
        )

        save_post(post_path, new_content)

        final_content = load_post(post_path)
        final_count = count_article_images(
            final_content
        )

        print("")
        print(
            f"Final images after save: "
            f"{final_count}"
        )

        verify_image_delta(
            before_count,
            final_count,
            inserted,
        )
        verify_expected_images(
            final_content,
            images,
        )
        verify_credits(final_content, images)

        print_image_state("Final", final_content)

        print("")
        print("Insertion summary:")
        print(f"  Images before: {before_count}")
        print(f"  Newly inserted: {inserted}")
        print(f"  Images after: {after_count}")
        print(
            f"  Expected equation: "
            f"{before_count} + {inserted} = "
            f"{before_count + inserted}"
        )

        if h2_numbers:
            print(
                "  Inserted/processed H2 numbers: "
                + ", ".join(
                    str(n) for n in h2_numbers
                )
            )

        print(
            "  Image Credits: Photo 1 through "
            "Photo 10"
        )
        print("")

        print(
            "Competitive images 6-10 are present "
            "in the published article."
        )
        print("Image verification passed.")

        print("=" * 70)
        print("INSERT COMPETITIVE IMAGES COMPLETE")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print("", file=sys.stderr)
        print(
            "Operation cancelled.",
            file=sys.stderr,
        )
        return 130

    except Exception as exc:
        print("", file=sys.stderr)
        print(
            "INSERT COMPETITIVE IMAGES FAILED",
            file=sys.stderr,
        )
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
