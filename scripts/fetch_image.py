#!/usr/bin/env python3

import json
import os
import shutil
import sys
import time

from pathlib import Path
from typing import Any, Dict, Optional

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"
IMAGE_DIR = ROOT_DIR / "static" / "images"

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30
IMAGE_COUNT = 5
MAX_PAGES = 3

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

MAX_ALLOWED_FAILED_IMAGES = 3

JPEG_MAGIC_BYTES = b"\xff\xd8\xff"
MIN_IMAGE_SIZE_BYTES = 1024


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Required environment variable "
            f"'{name}' is not set."
        )

    return value.strip()


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
            f"Could not read article.json: "
            f"{exc}"
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


def get_status_code(
    exception: Exception,
) -> Optional[int]:
    response = getattr(
        exception,
        "response",
        None,
    )

    if response is not None:
        status_code = getattr(
            response,
            "status_code",
            None,
        )

        if status_code is not None:
            return status_code

    return None


def get_retry_delay(
    response: Optional[requests.Response],
    attempt: int,
) -> int:
    if response is not None:
        retry_after = response.headers.get(
            "Retry-After"
        )

        if retry_after:
            try:
                return min(
                    int(retry_after),
                    60,
                )
            except ValueError:
                pass

    return min(
        2 ** (attempt - 1),
        8,
    )


def search_pexels(
    api_key: str,
    query: str,
    page: int = 1,
) -> Dict[str, Any]:
    headers = {
        "Authorization": api_key,
        "Accept": "application/json",
    }

    params = {
        "query": query,
        "orientation": "landscape",
        "size": "large",
        "per_page": 10,
        "page": page,
    }

    session = requests.Session()
    last_error: Optional[Exception] = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            response = session.get(
                PEXELS_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 403:
                raise requests.HTTPError(
                    f"403 Client Error: Forbidden "
                    f"for url: {response.url}",
                    response=response,
                )

            if (
                response.status_code
                in RETRYABLE_STATUS_CODES
            ):
                delay = get_retry_delay(
                    response,
                    attempt,
                )

                print(
                    f"Pexels returned HTTP "
                    f"{response.status_code}. "
                    f"Retry {attempt}/{MAX_RETRIES} "
                    f"after {delay} seconds..."
                )

                if attempt < MAX_RETRIES:
                    time.sleep(delay)
                    continue

                raise requests.HTTPError(
                    f"Pexels API request failed after "
                    f"{MAX_RETRIES} attempts with HTTP "
                    f"{response.status_code}",
                    response=response,
                )

            response.raise_for_status()

            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError(
                    "Pexels returned invalid JSON."
                ) from exc

        except requests.Timeout as exc:
            last_error = exc

            if attempt < MAX_RETRIES:
                delay = 2 ** (attempt - 1)

                print(
                    f"Pexels request timed out. "
                    f"Retry {attempt}/{MAX_RETRIES} "
                    f"after {delay} seconds..."
                )

                time.sleep(delay)
                continue

            raise RuntimeError(
                f"Pexels request timed out after "
                f"{MAX_RETRIES} attempts."
            ) from exc

        except requests.ConnectionError as exc:
            last_error = exc

            if attempt < MAX_RETRIES:
                delay = 2 ** (attempt - 1)

                print(
                    f"Pexels connection failed: {exc}. "
                    f"Retry {attempt}/{MAX_RETRIES} "
                    f"after {delay} seconds..."
                )

                time.sleep(delay)
                continue

            raise RuntimeError(
                f"Pexels connection failed after "
                f"{MAX_RETRIES} attempts: {exc}"
            ) from exc

        except requests.RequestException as exc:
            last_error = exc
            status_code = get_status_code(exc)

            if status_code == 403:
                raise RuntimeError(
                    f"Pexels API request failed "
                    f"with HTTP 403: {exc}"
                ) from exc

            if status_code in RETRYABLE_STATUS_CODES:
                if attempt < MAX_RETRIES:
                    delay = 2 ** (attempt - 1)

                    print(
                        f"Pexels request failed: {exc}. "
                        f"Retry {attempt}/{MAX_RETRIES} "
                        f"after {delay} seconds..."
                    )

                    time.sleep(delay)
                    continue

                raise RuntimeError(
                    f"Pexels API request failed: {exc}"
                ) from exc

            raise RuntimeError(
                f"Pexels API failed after "
                f"{MAX_RETRIES} attempts: "
                f"{last_error}"
            )

    raise RuntimeError(
        f"Pexels API failed after "
        f"{MAX_RETRIES} attempts: "
        f"{last_error}"
    )


def choose_photo(
    data: Dict[str, Any],
    used_photo_ids: set,
    used_photographers: set,
) -> Optional[Dict[str, Any]]:
    photos = data.get("photos")

    if not isinstance(photos, list):
        raise ValueError(
            "Pexels response does not contain "
            "a valid 'photos' list."
        )

    if not photos:
        return None

    candidates = []

    for photo in photos:
        if not isinstance(photo, dict):
            continue

        src = photo.get("src")

        if not isinstance(src, dict):
            continue

        image_url = (
            src.get("large2x")
            or src.get("large")
            or src.get("original")
        )

        if not image_url:
            continue

        photo_id = photo.get("id")
        photographer = (
            photo.get("photographer")
            or "Unknown photographer"
        )

        if photo_id in used_photo_ids:
            continue

        width = photo.get("width") or 0
        height = photo.get("height") or 0

        if width and height:
            aspect_ratio = width / height
        else:
            aspect_ratio = 0

        candidates.append(
            {
                "id": photo_id,
                "image_url": image_url,
                "photographer": photographer,
                "photographer_url": (
                    photo.get("photographer_url")
                    or ""
                ),
                "pexels_url": (
                    photo.get("url")
                    or ""
                ),
                "width": width,
                "height": height,
                "aspect_ratio": aspect_ratio,
            }
        )

    if not candidates:
        return None

    unique_photographer_candidates = [
        candidate
        for candidate in candidates
        if candidate["photographer"]
        not in used_photographers
    ]

    if unique_photographer_candidates:
        candidates = (
            unique_photographer_candidates
        )

    candidates.sort(
        key=lambda item: (
            item["aspect_ratio"],
            item["width"] * item["height"],
        ),
        reverse=True,
    )

    return candidates[0]


def download_image(
    image_url: str,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = destination.with_suffix(".tmp")

    try:
        with requests.get(
            image_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            response.raise_for_status()

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "",
                ).lower()
            )

            if (
                content_type
                and not content_type.startswith(
                    "image/"
                )
            ):
                raise RuntimeError(
                    "Pexels returned a non-image "
                    f"response with Content-Type: "
                    f"{content_type}"
                )

            with temp_path.open("wb") as file:
                for chunk in response.iter_content(
                    chunk_size=1024 * 64
                ):
                    if chunk:
                        file.write(chunk)

        validate_jpeg_file(temp_path)
        temp_path.replace(destination)
        validate_jpeg_file(destination)

    except requests.RequestException as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

        raise RuntimeError(
            f"Could not download image from Pexels: "
            f"{exc}"
        ) from exc

    except OSError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

        raise RuntimeError(
            f"Could not save downloaded image: "
            f"{exc}"
        ) from exc


def validate_jpeg_file(
    image_path: Path,
) -> None:
    if not image_path.exists():
        raise RuntimeError(
            "Image file was not created."
        )

    file_size = image_path.stat().st_size

    if file_size <= MIN_IMAGE_SIZE_BYTES:
        raise RuntimeError(
            f"Image file is too small: "
            f"{file_size} bytes."
        )

    with image_path.open("rb") as file:
        magic = file.read(3)

    if magic != JPEG_MAGIC_BYTES:
        raise RuntimeError(
            "Downloaded file is not a valid JPEG "
            "(missing FF D8 FF magic bytes)."
        )


def build_fallback_queries(
    query: str,
) -> list:
    words = [
        word
        for word in query.split()
        if word.strip()
    ]

    fallbacks = []

    first_four = " ".join(words[:4]).strip()

    if first_four:
        fallbacks.append(first_four)

    first_two = " ".join(words[:2]).strip()

    if first_two:
        fallbacks.append(first_two)

    fallbacks.append("bathroom organization")
    fallbacks.append("organized home interior")

    result = []
    seen = set()

    for fallback in fallbacks:
        normalized = fallback.strip()

        if not normalized:
            continue

        key = normalized.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(normalized)

    return result


def search_with_fallbacks(
    api_key: str,
    original_query: str,
    used_photo_ids: set,
    used_photographers: set,
) -> Optional[Dict[str, Any]]:
    fallback_queries = build_fallback_queries(
        original_query
    )

    all_queries = [original_query]

    for fallback in fallback_queries:
        if (
            fallback.lower()
            != original_query.lower()
        ):
            all_queries.append(fallback)

    for query_index, query in enumerate(
        all_queries
    ):
        is_original = query_index == 0

        if not is_original:
            print(
                f'HTTP 403 for query: '
                f'"{original_query}", '
                f'trying fallback query: '
                f'"{query}"'
            )

        for page in range(
            1,
            MAX_PAGES + 1,
        ):
            try:
                data = search_pexels(
                    api_key,
                    query,
                    page=page,
                )
            except RuntimeError as exc:
                message = str(exc)

                if (
                    "HTTP 403" in message
                    or "403 Client Error" in message
                ):
                    break

                raise

            photo = choose_photo(
                data,
                used_photo_ids,
                used_photographers,
            )

            if photo is not None:
                if not is_original:
                    print(
                        f'Fallback query succeeded: '
                        f'"{query}"'
                    )

                return photo

            print(
                f"No unused Pexels image found on "
                f"page {page} for query: {query}"
            )

    return None


def copy_reused_image(
    source_path: Path,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copyfile(
        source_path,
        destination,
    )

    validate_jpeg_file(destination)


def create_reused_image(
    successful_image: Dict[str, Any],
    destination: Path,
    failed_index: int,
) -> Dict[str, Any]:
    source_path = ROOT_DIR / (
        successful_image["file_path"]
    )

    if not source_path.exists():
        raise RuntimeError(
            "Could not reuse previous image because "
            f"source file does not exist: "
            f"{source_path}"
        )

    copy_reused_image(
        source_path,
        destination,
    )

    print(
        f"Reusing image "
        f"{successful_image['index']} "
        f"for failed image {failed_index}."
    )
    print(
        f"Reuse source: "
        f"{successful_image['file']}"
    )
    print(
        f"Reuse destination: "
        f"{destination}"
    )

    return {
        "index": failed_index,
        "query": (
            f"reuse:{successful_image['query']}"
        ),
        "file": (
            f"/images/{destination.name}"
        ),
        "file_path": str(
            destination.relative_to(ROOT_DIR)
        ),
        "photographer": (
            successful_image["photographer"]
        ),
        "photographer_url": (
            successful_image["photographer_url"]
        ),
        "pexels_url": (
            successful_image["pexels_url"]
        ),
        "image_source_url": (
            successful_image["image_source_url"]
        ),
        "image_id": successful_image["image_id"],
        "width": successful_image.get("width"),
        "height": successful_image.get("height"),
        "reused": True,
        "reuse_source_index": (
            successful_image["index"]
        ),
    }


def download_all_images(
    api_key: str,
    slug: str,
    image_queries: list,
) -> list:
    if len(image_queries) != IMAGE_COUNT:
        raise ValueError(
            f"Exactly {IMAGE_COUNT} image queries "
            "are required."
        )

    IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    images = []
    used_photo_ids = set()
    used_photographers = set()

    failed_images = 0

    for index, query in enumerate(
        image_queries,
        start=1,
    ):
        query = str(query).strip()

        if not query:
            raise ValueError(
                f"Image query {index} is empty."
            )

        print("")
        print("=" * 70)

        if index == 1:
            label = "HERO"
        else:
            label = f"H2 #{index - 1}"

        print(
            f"Downloading image {index}/"
            f"{IMAGE_COUNT} [{label}]"
        )
        print(f"Query: {query}")

        filename = f"{slug}-{index}.jpg"
        image_path = IMAGE_DIR / filename

        photo = None

        try:
            photo = search_with_fallbacks(
                api_key,
                query,
                used_photo_ids,
                used_photographers,
            )
        except Exception as exc:
            print(
                f"WARNING: image {index} search "
                f"failed: {exc}"
            )

        if photo is not None:
            image_url = photo["image_url"]
            photographer = photo["photographer"]
            photographer_url = (
                photo["photographer_url"]
            )
            pexels_url = photo["pexels_url"]
            photo_id = photo.get("id")

            print(
                f"Selected photographer: "
                f"{photographer}"
            )
            print(
                f"Selected image ID: "
                f"{photo_id}"
            )
            print(f"Image URL: {image_url}")
            print(f"Destination: {image_path}")

            try:
                download_image(
                    image_url,
                    image_path,
                )
            except Exception as exc:
                print(
                    f"WARNING: image {index} "
                    f"download failed: {exc}"
                )
                photo = None

        if photo is not None:
            if photo_id is not None:
                used_photo_ids.add(photo_id)

            if photographer:
                used_photographers.add(
                    photographer
                )

            images.append(
                {
                    "index": index,
                    "query": query,
                    "file": (
                        f"/images/{filename}"
                    ),
                    "file_path": str(
                        image_path.relative_to(
                            ROOT_DIR
                        )
                    ),
                    "photographer": photographer,
                    "photographer_url": (
                        photographer_url
                    ),
                    "pexels_url": pexels_url,
                    "image_source_url": (
                        image_url
                    ),
                    "image_id": photo_id,
                    "width": photo.get("width"),
                    "height": photo.get("height"),
                    "reused": False,
                }
            )
            continue

        failed_images += 1

        print(
            f"All fallback queries failed "
            f"for image #{index}"
        )

        if not images:
            print(
                "No successful image is available "
                "for reuse."
            )
        elif (
            failed_images
            <= MAX_ALLOWED_FAILED_IMAGES
        ):
            reuse_source = images[
                (failed_images - 1) % len(images)
            ]

            try:
                reused = create_reused_image(
                    reuse_source,
                    image_path,
                    index,
                )

                images.append(reused)

                print(
                    f"WARNING: image {index} "
                    f"was created by reusing a "
                    f"successful previous image."
                )
            except Exception as exc:
                print(
                    f"ERROR: reuse failed for "
                    f"image {index}: {exc}"
                )

        if failed_images >= 4:
            raise RuntimeError(
                f"{failed_images} images failed. "
                "At least 4 image failures are "
                "considered fatal."
            )

    if failed_images == 0:
        print("")
        print("=" * 70)
        print(
            f"All {IMAGE_COUNT} images downloaded "
            "successfully."
        )
        print("=" * 70)
    elif failed_images <= 3:
        print("")
        print("=" * 70)
        print(
            f"WARNING: {failed_images} image(s) "
            "failed and were handled with "
            "fallback/reuse."
        )
        print(
            f"Usable images: {len(images)}/"
            f"{IMAGE_COUNT}"
        )
        print("=" * 70)

    if len(images) != IMAGE_COUNT:
        raise RuntimeError(
            f"Could not produce exactly "
            f"{IMAGE_COUNT} usable images. "
            f"Produced {len(images)}."
        )

    return images


def main() -> int:
    try:
        print("=" * 70)
        print("Pexels image downloader")
        print("=" * 70)

        api_key = get_required_env(
            "PEXELS_API_KEY"
        )

        article = load_article()

        slug = article.get("slug")
        image_queries = article.get(
            "image_queries"
        )

        if (
            not isinstance(slug, str)
            or not slug.strip()
        ):
            raise ValueError(
                "article.json is missing "
                "a valid 'slug'."
            )

        if not isinstance(
            image_queries,
            list,
        ):
            raise ValueError(
                "article.json is missing "
                "the 'image_queries' array."
            )

        if len(image_queries) != IMAGE_COUNT:
            raise ValueError(
                f"article.json must contain "
                f"exactly {IMAGE_COUNT} "
                "image queries."
            )

        slug = slug.strip()
        normalized_queries = []

        for index, query in enumerate(
            image_queries,
            start=1,
        ):
            if not isinstance(
                query,
                str,
            ):
                raise ValueError(
                    f"Image query {index} "
                    "must be a string."
                )

            query = query.strip()

            if not query:
                raise ValueError(
                    f"Image query {index} "
                    "is empty."
                )

            if query not in normalized_queries:
                normalized_queries.append(
                    query
                )

        if (
            len(normalized_queries)
            != IMAGE_COUNT
        ):
            raise ValueError(
                "Image queries must be unique."
            )

        images = download_all_images(
            api_key,
            slug,
            normalized_queries,
        )

        article["image_queries"] = (
            normalized_queries
        )
        article["images"] = images
        article["image"] = (
            images[0]["file"]
        )
        article["image_file"] = (
            images[0]["file_path"]
        )
        article["photographer"] = (
            images[0]["photographer"]
        )
        article["photographer_url"] = (
            images[0]["photographer_url"]
        )
        article["pexels_url"] = (
            images[0]["pexels_url"]
        )
        article["image_source_url"] = (
            images[0]["image_source_url"]
        )
        article["image_id"] = (
            images[0]["image_id"]
        )

        save_article(article)

        print("")
        print("=" * 70)
        print(
            "Image metadata saved successfully."
        )
        print(
            f"Article JSON: {ARTICLE_PATH}"
        )
        print("")

        for image in images:
            reuse_marker = ""

            if image.get("reused"):
                reuse_marker = " [REUSED]"

            print(
                f"{image['index']}. "
                f"{image['file']} "
                f"← {image['query']}"
                f"{reuse_marker}"
            )

        print("=" * 70)
        print("FINAL IMAGE FETCH SUMMARY")
        print("=" * 70)

        successful_count = (
            IMAGE_COUNT
            - sum(
                1
                for image in images
                if image.get("reused")
            )
        )

        reused_count = sum(
            1
            for image in images
            if image.get("reused")
        )

        print(
            f"Requested images: {IMAGE_COUNT}"
        )
        print(
            f"Successful Pexels images: "
            f"{successful_count}"
        )
        print(
            f"Reused images: {reused_count}"
        )
        print(
            f"Total usable images: "
            f"{len(images)}"
        )

        if reused_count:
            print(
                "WARNING: Some images were "
                "reused because Pexels queries "
                "failed."
            )
        else:
            print(
                "STATUS: All requested images "
                "were fetched from Pexels."
            )

        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print(
            "\nOperation cancelled by user.",
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
