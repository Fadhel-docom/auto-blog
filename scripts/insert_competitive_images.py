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
            f"article.json field '{field_name}' is empty."
        )

    return value


def get_post_path(slug: str) -> Path:
    return POSTS_DIR / f"{slug}.md"


def load_post(post_path: Path) -> str:
    if not post_path.exists():
        raise FileNotFoundError(
            f"Published post was not found: {post_path}"
        )

    try:
        content = post_path.read_text(
            encoding="utf-8"
        )

    except OSError as exc:
        raise RuntimeError(
            f"Could not read published post: {exc}"
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


def extract_image_paths(
    content: str,
) -> List[str]:
    matches = re.findall(
        r"!\[[^\]]*\]\(([^)\s]+)",
        content,
    )

    return [
        str(match).strip()
        for match in matches
        if str(match).strip()
    ]


def normalize_image_path(
    file_value: str,
) -> str:
    file_value = str(file_value).strip()

    while (
        file_value.startswith("../")
        or file_value.startswith("./")
        or file_value.startswith("/")
    ):
        if file_value.startswith("../"):
            file_value = file_value[3:]
        elif file_value.startswith("./"):
            file_value = file_value[2:]
        else:
            file_value = file_value[1:]

    if file_value.startswith("images/"):
        file_value = file_value[len("images/"):]

    return file_value.strip()


def extract_frontmatter(
    content: str,
) -> str:
    if not isinstance(content, str):
        return ""

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


def detect_frontmatter_format(
    content: str,
) -> Optional[str]:
    if not isinstance(content, str):
        return None

    if re.match(
        r"^\+\+\+\s*\n",
        content,
    ):
        return "toml"

    if re.match(
        r"^---\s*\n",
        content,
    ):
        return "yaml"

    return None


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

    yaml_quoted_match = re.search(
        r'^\s*image\s*:\s*["\']([^"\']*)["\']\s*(?:#.*)?$',
        frontmatter,
        flags=re.MULTILINE,
    )

    if yaml_quoted_match:
        value = yaml_quoted_match.group(1).strip()

        if value:
            return normalize_image_path(value)

    yaml_unquoted_match = re.search(
        r'^\s*image\s*:\s*([^\s#]+)\s*(?:#.*)?$',
        frontmatter,
        flags=re.MULTILINE,
    )

    if yaml_unquoted_match:
        value = yaml_unquoted_match.group(1).strip()

        if value:
            return normalize_image_path(value)

    return None


def get_existing_image_paths(
    content: str,
) -> set:
    paths = set()

    for path in extract_image_paths(content):
        normalized = normalize_image_path(path)

        if normalized:
            paths.add(normalized)

    hero_path = extract_hero_image_path(content)

    if hero_path:
        paths.add(hero_path)

    return paths


def count_article_images(
    content: str,
) -> int:
    return len(
        get_existing_image_paths(content)
    )


def build_markdown_image(
    image: Dict[str, Any],
) -> str:
    file_value = image.get("file", "")

    if not isinstance(file_value, str):
        raise ValueError(
            "Image file must be a string."
        )

    filename = normalize_image_path(
        file_value
    )

    if not filename:
        raise ValueError(
            "Image has an empty file path."
        )

    alt_text = image.get("query", "")

    if not isinstance(alt_text, str):
        alt_text = ""

    alt_text = alt_text.strip()

    if not alt_text:
        alt_text = "Home organization image"

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
            f"Expected exactly {REQUIRED_IMAGES} images "
            f"in article.json, got {len(images)}."
        )

    validated = []

    for index, image in enumerate(
        images,
        start=1,
    ):
        if not isinstance(image, dict):
            raise ValueError(
                f"Image #{index} must be an object."
            )

        file_value = image.get(
            "file",
            "",
        )

        if (
            not isinstance(file_value, str)
            or not file_value.strip()
        ):
            raise ValueError(
                f"Image #{index} has no valid file."
            )

        filename = normalize_image_path(
            file_value
        )

        expected_filename = (
            f"{article['slug']}-{index}.jpg"
        )

        if filename != expected_filename:
            raise ValueError(
                f"Image #{index} filename mismatch. "
                f"Expected '{expected_filename}', "
                f"got '{filename}'."
            )

        image_path = (
            IMAGE_DIR / expected_filename
        )

        if not image_path.exists():
            raise FileNotFoundError(
                f"Image #{index} is missing from disk: "
                f"{image_path}"
            )

        if image_path.stat().st_size <= 0:
            raise ValueError(
                f"Image #{index} is empty: "
                f"{image_path}"
            )

        query = image.get(
            "query",
            "",
        )

        if (
            not isinstance(query, str)
            or not query.strip()
        ):
            raise ValueError(
                f"Image #{index} has no "
                "query/alt text."
            )

        validated.append(image)

    return validated


def is_h2_line(
    line: str,
) -> bool:
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
    if len(images) != REQUIRED_IMAGES:
        raise ValueError(
            f"Expected {REQUIRED_IMAGES} images."
        )

    additional_images = images[
        EXISTING_PUBLISHED_IMAGES:
    ]

    if len(additional_images) != ADDITIONAL_IMAGES:
        raise ValueError(
            "Could not obtain exactly five "
            "additional images."
        )

    existing_image_paths = (
        get_existing_image_paths(content)
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

        if (
            h2_count
            < EXISTING_PUBLISHED_IMAGES + 1
        ):
            continue

        target_index = (
            h2_count
            - EXISTING_PUBLISHED_IMAGES
            - 1
        )

        if (
            target_index < 0
            or target_index >= len(additional_images)
        ):
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

        image_markdown = build_markdown_image(
            image
        )

        if filename in existing_image_paths:
            print(
                f"Image {image_number} already "
                "exists in the post; "
                "skipping duplicate."
            )

            inserted_h2_numbers.append(
                h2_count
            )

            continue

        output.append("")
        output.append(image_markdown)
        output.append("")

        inserted += 1

        inserted_h2_numbers.append(
            h2_count
        )

        existing_image_paths.add(
            filename
        )

        print(
            f"Inserted image {image_number} "
            f"after H2 #{h2_count}."
        )

    if processed_targets < ADDITIONAL_IMAGES:
        print(
            "WARNING: only "
            f"{processed_targets}/"
            f"{ADDITIONAL_IMAGES} target "
            "image positions were found."
        )

    return (
        "\n".join(output),
        inserted,
        inserted_h2_numbers,
    )


def verify_image_delta(
    before_count: int,
    after_count: int,
    inserted_count: int,
) -> None:
    expected_after = (
        before_count + inserted_count
    )

    if after_count != expected_after:
        raise RuntimeError(
            "Image count verification failed: "
            f"before={before_count}, "
            f"newly_inserted={inserted_count}, "
            f"expected_after={expected_after}, "
            f"actual_after={after_count}."
        )


def verify_additional_images_present(
    content: str,
    images: List[Dict[str, Any]],
) -> None:
    if len(images) != REQUIRED_IMAGES:
        raise ValueError(
            f"Expected {REQUIRED_IMAGES} images."
        )

    existing_image_paths = (
        get_existing_image_paths(content)
    )

    missing = []

    for index in range(
        EXISTING_PUBLISHED_IMAGES + 1,
        REQUIRED_IMAGES + 1,
    ):
        image = images[index - 1]

        filename = normalize_image_path(
            image.get("file", "")
        )

        if not filename:
            missing.append(index)
            continue

        if filename not in existing_image_paths:
            missing.append(index)

    if missing:
        missing_text = ", ".join(
            str(index)
            for index in missing
        )

        raise RuntimeError(
            "The published post is missing "
            f"additional image(s): {missing_text}"
        )


def verify_expected_base_images(
    content: str,
    images: List[Dict[str, Any]],
) -> None:
    if len(images) != REQUIRED_IMAGES:
        raise ValueError(
            f"Expected {REQUIRED_IMAGES} images."
        )

    existing_image_paths = (
        get_existing_image_paths(content)
    )

    missing = []

    for index in range(
        1,
        EXISTING_PUBLISHED_IMAGES + 1,
    ):
        image = images[index - 1]

        filename = normalize_image_path(
            image.get("file", "")
        )

        if not filename:
            missing.append(index)
            continue

        if filename not in existing_image_paths:
            missing.append(index)

    if missing:
        missing_text = ", ".join(
            str(index)
            for index in missing
        )

        raise RuntimeError(
            "The published post is missing "
            f"base image(s): {missing_text}"
        )


def print_image_state(
    label: str,
    content: str,
) -> None:
    image_paths = sorted(
        get_existing_image_paths(content)
    )

    print("")
    print(f"{label} image state:")
    print(f"  Total images: {len(image_paths)}")

    hero_path = extract_hero_image_path(
        content
    )

    if hero_path:
        print(
            f"  Hero image: {hero_path}"
        )
    else:
        print("  Hero image: none")

    markdown_paths = [
        normalize_image_path(path)
        for path in extract_image_paths(content)
        if normalize_image_path(path)
    ]

    print(
        f"  Markdown image references: "
        f"{len(markdown_paths)}"
    )

    if image_paths:
        print("  Image files:")

        for index, path in enumerate(
            image_paths,
            start=1,
        ):
            print(
                f"    {index}. {path}"
            )

    print("")


def main() -> int:
    print("=" * 70)
    print("INSERT COMPETITIVE IMAGES")
    print("=" * 70)

    try:
        article = load_article()

        slug = get_required_string(
            article,
            "slug",
        )

        images = validate_images(
            article
        )

        post_path = get_post_path(slug)

        content = load_post(
            post_path
        )

        frontmatter_format = (
            detect_frontmatter_format(
                content
            )
        )

        if frontmatter_format:
            print(
                "Frontmatter format detected: "
                f"{frontmatter_format.upper()}"
            )
        else:
            print(
                "Frontmatter format detected: "
                "none"
            )

        before_count = count_article_images(
            content
        )

        print(
            f"Post: {post_path}"
        )

        print(
            f"Images before insertion: "
            f"{before_count}"
        )

        print(
            f"Images available in article.json: "
            f"{len(images)}"
        )

        hero_path = extract_hero_image_path(
            content
        )

        if hero_path:
            print(
                f"Hero image in frontmatter: "
                f"{hero_path}"
            )
        else:
            print(
                "Hero image in frontmatter: none"
            )

        print_image_state(
            "Before",
            content,
        )

        if before_count >= REQUIRED_IMAGES:
            print(
                "The post already contains at least "
                f"{REQUIRED_IMAGES} images."
            )

            verify_expected_base_images(
                content,
                images,
            )

            verify_additional_images_present(
                content,
                images,
            )

            print(
                "All required image files are already "
                "present; no insertion is required."
            )

            print("=" * 70)
            print(
                "INSERT COMPETITIVE IMAGES COMPLETE"
            )
            print("=" * 70)

            return 0

        if before_count < MARKDOWN_EXISTING_IMAGES:
            raise RuntimeError(
                "The published post contains fewer "
                "than "
                f"{MARKDOWN_EXISTING_IMAGES} "
                "total images. "
                "The original publisher did not "
                "create the expected base article."
            )

        print(
            "Existing image count is below the "
            f"{REQUIRED_IMAGES}-image target."
        )

        print(
            "Adding competitive images 6-10 "
            "after H2 #6 through H2 #10."
        )

        new_content, inserted, h2_numbers = (
            insert_additional_images(
                content,
                images,
            )
        )

        after_count = count_article_images(
            new_content
        )

        print("")
        print(
            f"Images before insertion: "
            f"{before_count}"
        )

        print(
            f"Newly inserted images: "
            f"{inserted}"
        )

        print(
            f"Images after insertion: "
            f"{after_count}"
        )

        verify_image_delta(
            before_count,
            after_count,
            inserted,
        )

        verify_expected_base_images(
            new_content,
            images,
        )

        verify_additional_images_present(
            new_content,
            images,
        )

        print(
            "Pre-save verification passed."
        )

        save_post(
            post_path,
            new_content,
        )

        final_content = load_post(
            post_path
        )

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

        verify_expected_base_images(
            final_content,
            images,
        )

        verify_additional_images_present(
            final_content,
            images,
        )

        print_image_state(
            "Final",
            final_content,
        )

        print("")
        print("Insertion summary:")

        print(
            f"  Images before: "
            f"{before_count}"
        )

        print(
            f"  Newly inserted: "
            f"{inserted}"
        )

        print(
            f"  Images after: "
            f"{after_count}"
        )

        print(
            "  Expected equation: "
            f"{before_count} + "
            f"{inserted} = "
            f"{before_count + inserted}"
        )

        print(
            "  Inserted/processed H2 numbers: "
            + ", ".join(
                str(number)
                for number in h2_numbers
            )
        )

        print("")

        print(
            "Competitive images 6-10 are present "
            "in the published article."
        )

        print(
            "Image verification passed."
        )

        print("=" * 70)
        print(
            "INSERT COMPETITIVE IMAGES COMPLETE"
        )
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print(
            "",
            file=sys.stderr,
        )

        print(
            "Operation cancelled.",
            file=sys.stderr,
        )

        return 130

    except Exception as exc:
        print(
            "",
            file=sys.stderr,
        )

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
    sys.exit(
        main()
    )
