#!/usr/bin/env python3

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"

ARTICLE_PATH = ROOT_DIR / "article.json"
POSTS_DIR = ROOT_DIR / "content" / "posts"

REQUIRED_IMAGES = 6
PUBLISH_IMAGES = 6


def configure_python_path() -> None:
    scripts_path = str(SCRIPTS_DIR)

    if scripts_path not in sys.path:
        sys.path.insert(
            0,
            scripts_path,
        )


def import_original_publisher():
    configure_python_path()

    try:
        import publish

    except ImportError as exc:
        raise RuntimeError(
            "Could not import scripts/publish.py."
        ) from exc

    return publish


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
            f"article.json contains invalid JSON: {exc}"
        ) from exc

    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain a JSON object."
        )

    return article


def save_article(article: Dict[str, Any]) -> None:
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")

    try:
        with temp_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                article,
                file,
                ensure_ascii=False,
                indent=2,
            )

            file.write("\n")

        temp_path.replace(ARTICLE_PATH)

    except OSError as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        raise RuntimeError(
            f"Could not save article.json: {exc}"
        ) from exc


def validate_article(article: Dict[str, Any]) -> None:
    slug = article.get("slug")

    if not isinstance(slug, str) or not slug.strip():
        raise ValueError(
            "article.json is missing a valid slug."
        )

    images = article.get("images")

    if not isinstance(images, list):
        raise ValueError(
            "article.json must contain an images list."
        )

    if len(images) != REQUIRED_IMAGES:
        raise ValueError(
            f"Expected exactly {REQUIRED_IMAGES} images "
            f"before publishing, got {len(images)}."
        )

    for index, image in enumerate(images, start=1):
        if not isinstance(image, dict):
            raise ValueError(
                f"Image #{index} must be an object."
            )

        file_value = image.get("file", "")

        if not isinstance(file_value, str) or not file_value.strip():
            raise ValueError(
                f"Image #{index} has no valid file."
            )


def create_publish_article(
    original_article: Dict[str, Any],
) -> Dict[str, Any]:
    publish_article = dict(original_article)

    original_images = list(original_article["images"])

    publish_article["images"] = original_images[:PUBLISH_IMAGES]

    first_image = original_images[0]

    if not publish_article.get("image"):
        first_file = first_image.get("file", "")

        if isinstance(first_file, str) and first_file.strip():
            publish_article["image"] = first_file

    return publish_article


def get_post_path(article: Dict[str, Any]) -> Path:
    slug = str(article.get("slug", "")).strip()

    if not slug:
        raise ValueError("Article slug is empty.")

    return POSTS_DIR / f"{slug}.md"


def backup_existing_post(
    post_path: Path,
) -> Optional[Path]:
    if not post_path.exists():
        return None

    backup_path = post_path.with_suffix(
        ".md.competitive-backup"
    )

    if backup_path.exists():
        backup_path.unlink()

    shutil.copy2(post_path, backup_path)

    return backup_path


def restore_existing_post(
    post_path: Path,
    backup_path: Optional[Path],
) -> None:
    if backup_path is not None:
        if backup_path.exists():
            shutil.copy2(backup_path, post_path)
            backup_path.unlink()

        return

    if post_path.exists():
        post_path.unlink()


def remove_backup(backup_path: Optional[Path]) -> None:
    if backup_path is not None and backup_path.exists():
        backup_path.unlink()


def run_original_publisher(publish_module) -> int:
    result = publish_module.main()

    if result is None:
        return 0

    if not isinstance(result, int):
        return 0

    return result


def main() -> int:
    print("=" * 70)
    print("COMPETITIVE PUBLISH WRAPPER")
    print("=" * 70)

    original_article = load_article()

    validate_article(original_article)

    post_path = get_post_path(original_article)

    backup_path = backup_existing_post(post_path)

    temporary_article = create_publish_article(
        original_article
    )

    print(
        f"Original images: "
        f"{len(original_article['images'])}"
    )

    print(
        f"Images exposed to publish.py: "
        f"{len(temporary_article['images'])}"
    )

    print(f"Target post: {post_path}")

    publish_module = None
    publish_result = 1

    try:
        print("")
        print(
            "Writing temporary 5-image article.json..."
        )

        save_article(temporary_article)

        publish_module = import_original_publisher()

        print("Original publisher imported successfully.")
        print("Running publish.py...")

        publish_result = run_original_publisher(
            publish_module
        )

        if publish_result != 0:
            raise RuntimeError(
                "publish.py returned "
                f"exit code {publish_result}."
            )

        if not post_path.exists():
            raise RuntimeError(
                "publish.py completed without creating "
                f"the expected post: {post_path}"
            )

        if post_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Published post is empty: {post_path}"
            )

        print("")
        print("publish.py completed successfully.")
        print(f"Published post exists: {post_path}")
        print(
            f"Published post size: "
            f"{post_path.stat().st_size} bytes"
        )

        remove_backup(backup_path)
        backup_path = None

        return 0

    except Exception as exc:
        print("", file=sys.stderr)
        print("COMPETITIVE PUBLISH FAILED", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            "Restoring previous post state...",
            file=sys.stderr,
        )

        try:
            restore_existing_post(
                post_path,
                backup_path,
            )
            backup_path = None
            print(
                "Previous post state restored.",
                file=sys.stderr,
            )

        except Exception as restore_exc:
            print(
                "WARNING: Could not restore previous "
                f"post state: {restore_exc}",
                file=sys.stderr,
            )

        return 1

    finally:
        print("")
        print(
            "Restoring original 10-image article.json..."
        )

        try:
            save_article(original_article)
            print("article.json restored successfully.")

        except Exception as restore_article_exc:
            print(
                "CRITICAL: Could not restore "
                "original article.json.",
                file=sys.stderr,
            )
            print(
                f"ERROR: {restore_article_exc}",
                file=sys.stderr,
            )

            if publish_result == 0:
                publish_result = 1

        if backup_path is not None:
            remove_backup(backup_path)

    print("=" * 70)
    print("COMPETITIVE PUBLISH WRAPPER COMPLETE")
    print("=" * 70)

    return publish_result


if __name__ == "__main__":
    try:
        sys.exit(main())

    except KeyboardInterrupt:
        print("", file=sys.stderr)
        print("Operation cancelled.", file=sys.stderr)
        sys.exit(130)

    except Exception as exc:
        print("", file=sys.stderr)
        print(f"FATAL ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
