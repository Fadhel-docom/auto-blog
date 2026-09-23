#!/usr/bin/env python3

import hashlib
import json
import os
import sys
import time

from pathlib import Path
from typing import Any, Dict, Optional, Set

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

JPEG_MAGIC_BYTES = b"\xff\xd8\xff"
MIN_IMAGE_SIZE_BYTES = 1024
HASH_CHUNK_SIZE = 1024 * 64


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
    temp_path = ARTICLE_PATH.with_suffix(
        ".json.tmp"
    )

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
            ) from exc

    raise RuntimeError(
        f"Pexels API failed after "
        f"{MAX_RETRIES} attempts: "
        f"{last_error}"
    )


def choose_photo(
    data: Dict[str, Any],
    used_photo_ids: Set[Any],
    used_photographers: Set[str],
) -> list:
    photos = data.get("photos")

    if not isinstance(photos, list):
        raise ValueError(
            "Pexels response does not contain "
            "a valid 'photos' list."
        )

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

        if photo_id in used_photo_ids:
            continue

        photographer = (
            photo.get("photographer")
            or "Unknown photographer"
        )

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
        return []

    unique_photographers = [
        candidate
        for candidate in candidates
        if candidate["photographer"]
        not in used_photographers
    ]

    if unique_photographers:
        candidates = unique_photographers

    candidates.sort(
        key=lambda item: (
            item["aspect_ratio"],
            item["width"] * item["height"],
        ),
        reverse=True,
    )

    return candidates


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


def calculate_sha256(
    image_path: Path,
) -> str:
    digest = hashlib.sha256()

    with image_path.open("rb") as file:
        while True:
            chunk = file.read(HASH_CHUNK_SIZE)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def collect_existing_image_hashes() -> Set[str]:
    hashes: Set[str] = set()

    if not IMAGE_DIR.exists():
        return hashes

    for image_path in IMAGE_DIR.glob("*.jpg"):
        try:
            validate_jpeg_file(image_path)
            image_hash = calculate_sha256(
                image_path
            )
            hashes.add(image_hash)

        except (OSError, RuntimeError) as exc:
            print(
                f"WARNING: could not hash existing "
                f"image {image_path}: {exc}"
            )

    print(
        f"Existing image hashes loaded: "
        f"{len(hashes)}"
    )

    return hashes


def download_image(
    image_url: str,
    destination: Path,
    existing_hashes: Set[str],
) -> str:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = destination.with_suffix(
        ".tmp"
    )

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
                    chunk_size=HASH_CHUNK_SIZE
                ):
                    if chunk:
                        file.write(chunk)

        validate_jpeg_file(temp_path)

        image_hash = calculate_sha256(
            temp_path
        )

        if image_hash in existing_hashes:
            print(
                "DUPLICATE IMAGE DETECTED: "
                f"{image_hash}"
            )

            temp_path.unlink(
                missing_ok=True
            )

            return ""

        temp_path.replace(destination)

        validate_jpeg_file(destination)

        return image_hash

    except requests.RequestException as exc:
        temp_path.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            f"Could not download image from Pexels: "
            f"{exc}"
        ) from exc

    except OSError as exc:
        temp_path.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            f"Could not save downloaded image: "
            f"{exc}"
        ) from exc


def build_fallback_queries(
    query: str,
) -> list:
    words = [
        word
        for word in query.split()
        if word.strip()
    ]

    fallbacks = []

    first_four = " ".join(
        words[:4]
    ).strip()

    if first_four:
        fallbacks.append(first_four)

    first_two = " ".join(
        words[:2]
    ).strip()

    if first_two:
        fallbacks.append(first_two)

    fallbacks.append(
        "home organization interior"
    )

    fallbacks.append(
        "organized small space"
    )

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


def search_queries(
    original_query: str,
) -> list:
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

    return all_queries


def find_unique_photo(
    api_key: str,
    original_query: str,
    used_photo_ids: Set[Any],
    used_photographers: Set[str],
    existing_hashes: Set[str],
    destination: Path,
) -> Optional[Dict[str, Any]]:
    queries = search_queries(
        original_query
    )

    for query_index, query in enumerate(
        queries
    ):
        is_original = query_index == 0

        if not is_original:
            print(
                f'Trying fallback query: "{query}"'
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

            candidates = choose_photo(
                data,
                used_photo_ids,
                used_photographers,
            )

            if not candidates:
                print(
                    f"No unused Pexels images "
                    f"on page {page} for query: "
                    f"{query}"
                )
                continue

            for photo in candidates:
                photo_id = photo.get("id")

                print(
                    f"Testing Pexels image ID: "
                    f"{photo_id}"
                )

                try:
                    image_hash = download_image(
                        photo["image_url"],
                        destination,
                        existing_hashes,
                    )

                except Exception as exc:
                    print(
                        f"WARNING: download failed "
                        f"for image {photo_id}: "
                        f"{exc}"
                    )

                    if photo_id is not None:
                        used_photo_ids.add(
                            photo_id
                        )

                    continue

                if not image_hash:
                    print(
                        f"Rejected duplicate image "
                        f"ID: {photo_id}"
                    )

                    if photo_id is not None:
                        used_photo_ids.add(
                            photo_id
                        )

                    continue

                if photo_id is not None:
                    used_photo_ids.add(
                        photo_id
                    )

                photographer = (
                    photo["photographer"]
                )

                if photographer:
                    used_photographers.add(
                        photographer
                    )

                existing_hashes.add(
                    image_hash
                )

                return {
                    "photo": photo,
                    "image_hash": image_hash,
                }

            print(
                f"All candidates on page {page} "
                f"were rejected or failed."
            )

    return None


def download_all_images(
    api_key: str,
    slug: str,
    image_queries: list,
    existing_hashes: Set[str],
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
    used_photo_ids: Set[Any] = set()
    used_photographers: Set[str] = set()

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

        label = (
            "HERO"
            if index == 1
            else f"H2 #{index - 1}"
        )

        print(
            f"Downloading image {index}/"
            f"{IMAGE_COUNT} [{label}]"
        )
        print(f"Query: {query}")

        filename = f"{slug}-{index}.jpg"
        image_path = IMAGE_DIR / filename

        result = find_unique_photo(
            api_key,
            query,
            used_photo_ids,
            used_photographers,
            existing_hashes,
            image_path,
        )

        if result is None:
            raise RuntimeError(
                f"Could not find a unique Pexels "
                f"image for image #{index}: "
                f"{query}"
            )

        photo = result["photo"]
        image_hash = result["image_hash"]

        print(
            f"Selected photographer: "
            f"{photo['photographer']}"
        )
        print(
            f"Selected image ID: "
            f"{photo.get('id')}"
        )
        print(
            f"SHA-256: {image_hash}"
        )
        print(
            f"Destination: {image_path}"
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
                "photographer": (
                    photo["photographer"]
                ),
                "photographer_url": (
                    photo["photographer_url"]
                ),
                "pexels_url": (
                    photo["pexels_url"]
                ),
                "image_source_url": (
                    photo["image_url"]
                ),
                "image_id": photo.get("id"),
                "width": photo.get("width"),
                "height": photo.get("height"),
                "sha256": image_hash,
                "reused": False,
            }
        )

    print("")
    print("=" * 70)
    print(
        f"All {IMAGE_COUNT} images downloaded "
        "successfully."
    )
    print(
        "No image reuse is permitted."
    )
    print(
        "Duplicate image hashes are rejected."
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
        print("Duplicate protection enabled")
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

        existing_hashes = (
            collect_existing_image_hashes()
        )

        images = download_all_images(
            api_key,
            slug,
            normalized_queries,
            existing_hashes,
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

        article["image_sha256"] = (
            images[0]["sha256"]
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
            print(
                f"{image['index']}. "
                f"{image['file']} "
                f"← {image['query']}"
            )

        print("=" * 70)
        print("FINAL IMAGE FETCH SUMMARY")
        print("=" * 70)
        print(
            f"Requested images: {IMAGE_COUNT}"
        )
        print(
            f"Unique Pexels images: {len(images)}"
        )
        print(
            "Reused images: 0"
        )
        print(
            "Duplicate protection: ENABLED"
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
