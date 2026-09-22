#!/usr/bin/env python3

import json
import math
import os
import shutil
import sys
import time

from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"
IMAGE_DIR = ROOT_DIR / "static" / "images"

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

IMAGE_COUNT = 10
MAX_PAGES = 3
PER_PAGE = 10

TARGET_ASPECT_RATIO = 1.5

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

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


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(
            f"Required environment variable "
            f"'{name}' is not set."
        )

    return value.strip()


def get_status_code(exception: Exception) -> Optional[int]:
    response = getattr(exception, "response", None)

    if response is not None:
        return getattr(
            response,
            "status_code",
            None,
        )

    return getattr(
        exception,
        "status_code",
        None,
    )


def retry_delay(
    response: Optional[requests.Response],
    attempt: int,
) -> int:
    if response is not None:
        retry_after = response.headers.get("Retry-After")

        if retry_after:
            try:
                return min(int(retry_after), 60)
            except ValueError:
                pass

    return min(2 ** (attempt - 1), 8)


def search_pexels(
    api_key: str,
    query: str,
    page: int,
) -> Dict[str, Any]:
    headers = {
        "Authorization": api_key,
        "Accept": "application/json",
    }

    params = {
        "query": query,
        "orientation": "landscape",
        "size": "large",
        "per_page": PER_PAGE,
        "page": page,
    }

    session = requests.Session()

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                PEXELS_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 403:
                raise requests.HTTPError(
                    "Pexels returned HTTP 403.",
                    response=response,
                )

            if (
                response.status_code
                in RETRYABLE_STATUS_CODES
            ):
                if attempt < MAX_RETRIES:
                    delay = retry_delay(
                        response,
                        attempt,
                    )

                    print(
                        f"Pexels HTTP "
                        f"{response.status_code}; "
                        f"retry {attempt}/"
                        f"{MAX_RETRIES} "
                        f"after {delay}s..."
                    )

                    time.sleep(delay)
                    continue

            response.raise_for_status()

            data = response.json()

            if not isinstance(data, dict):
                raise ValueError(
                    "Pexels response is not an object."
                )

            return data

        except requests.Timeout as exc:
            last_exception = exc

            if attempt < MAX_RETRIES:
                delay = min(2 ** (attempt - 1), 8)
                time.sleep(delay)
                continue

            raise RuntimeError(
                "Pexels request timed out."
            ) from exc

        except requests.ConnectionError as exc:
            last_exception = exc

            if attempt < MAX_RETRIES:
                delay = min(2 ** (attempt - 1), 8)
                time.sleep(delay)
                continue

            raise RuntimeError(
                "Pexels connection failed."
            ) from exc

        except requests.RequestException as exc:
            last_exception = exc

            status = get_status_code(exc)

            if status == 403:
                raise RuntimeError(
                    "Pexels API request failed "
                    "with HTTP 403."
                ) from exc

            if (
                status in RETRYABLE_STATUS_CODES
                and attempt < MAX_RETRIES
            ):
                delay = min(2 ** (attempt - 1), 8)
                time.sleep(delay)
                continue

            raise RuntimeError(
                f"Pexels API request failed: {exc}"
            ) from exc

    raise RuntimeError(
        f"Pexels API failed: {last_exception}"
    )


def normalize_query(query: Any) -> str:
    if not isinstance(query, str):
        return ""

    return " ".join(query.strip().split())


def build_fallback_queries(query: str) -> List[str]:
    words = query.split()

    fallbacks = []

    if len(words) >= 4:
        fallbacks.append(" ".join(words[:6]))

    if len(words) >= 2:
        fallbacks.append(" ".join(words[:4]))

    fallbacks.extend(
        [
            "organized home storage interior",
            "small space storage organized room",
        ]
    )

    result = []
    seen = set()

    for item in fallbacks:
        item = normalize_query(item)

        if not item:
            continue

        key = item.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

    return result


def candidate_from_photo(
    photo: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    src = photo.get("src")

    if not isinstance(src, dict):
        return None

    image_url = (
        src.get("large2x")
        or src.get("large")
        or src.get("original")
    )

    if not image_url:
        return None

    photo_id = photo.get("id")

    if photo_id is None:
        return None

    width = int(photo.get("width") or 0)
    height = int(photo.get("height") or 0)

    if width <= 0 or height <= 0:
        return None

    aspect_ratio = width / height

    photographer = str(
        photo.get("photographer", "") or ""
    ).strip()

    return {
        "id": photo_id,
        "image_url": image_url,
        "photographer": photographer,
        "photographer_url": str(
            photo.get("photographer_url", "") or ""
        ).strip(),
        "pexels_url": str(
            photo.get("url", "") or ""
        ).strip(),
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
    }


def collect_candidates(
    api_key: str,
    query: str,
) -> List[Dict[str, Any]]:
    candidates = []
    seen_ids = set()

    queries = [query]

    for fallback in build_fallback_queries(query):
        if fallback.lower() != query.lower():
            queries.append(fallback)

    for query_index, current_query in enumerate(queries):
        try:
            for page in range(1, MAX_PAGES + 1):
                print(
                    f"  Searching page {page}/"
                    f"{MAX_PAGES}: "
                    f'"{current_query}"'
                )

                data = search_pexels(
                    api_key,
                    current_query,
                    page,
                )

                photos = data.get("photos", [])

                if not isinstance(photos, list):
                    continue

                for photo in photos:
                    if not isinstance(photo, dict):
                        continue

                    candidate = candidate_from_photo(
                        photo
                    )

                    if candidate is None:
                        continue

                    photo_id = candidate["id"]

                    if photo_id in seen_ids:
                        continue

                    seen_ids.add(photo_id)
                    candidate["matched_query"] = (
                        current_query
                    )
                    candidate["page"] = page
                    candidates.append(candidate)

        except RuntimeError as exc:
            print(
                f"  Search failed for "
                f'"{current_query}": {exc}',
                file=sys.stderr,
            )

            if query_index == 0:
                print(
                    "  Trying fallback queries..."
                )

            continue

        if candidates:
            break

    return candidates


def candidate_score(
    candidate: Dict[str, Any],
    used_photographers: set,
) -> float:
    aspect_ratio = float(
        candidate.get("aspect_ratio", 0) or 0
    )

    width = int(candidate.get("width", 0) or 0)
    height = int(candidate.get("height", 0) or 0)

    area = max(1, width * height)

    aspect_difference = abs(
        aspect_ratio - TARGET_ASPECT_RATIO
    )

    aspect_score = max(
        0.0,
        40.0 - (aspect_difference * 35.0),
    )

    photographer = str(
        candidate.get("photographer", "")
    ).strip()

    photographer_score = (
        25.0
        if photographer
        and photographer not in used_photographers
        else 0.0
    )

    area_score = min(
        20.0,
        math.log10(area) * 2.2,
    )

    page = int(candidate.get("page", 3) or 3)

    page_score = max(0.0, 4.0 - page)

    return (
        aspect_score
        + photographer_score
        + area_score
        + page_score
    )


def choose_best_candidate(
    candidates: List[Dict[str, Any]],
    used_photo_ids: set,
    used_photographers: set,
) -> Optional[Dict[str, Any]]:
    filtered = []

    for candidate in candidates:
        if candidate["id"] in used_photo_ids:
            continue

        filtered.append(candidate)

    if not filtered:
        return None

    unique_photographers = [
        candidate
        for candidate in filtered
        if candidate.get("photographer", "")
        not in used_photographers
    ]

    if unique_photographers:
        filtered = unique_photographers

    filtered.sort(
        key=lambda candidate: (
            candidate_score(
                candidate,
                used_photographers,
            ),
            candidate.get("width", 0)
            * candidate.get("height", 0),
        ),
        reverse=True,
    )

    return filtered[0]


def validate_jpeg_file(image_path: Path) -> None:
    if not image_path.exists():
        raise RuntimeError(
            "Image file was not created."
        )

    if image_path.stat().st_size <= MIN_IMAGE_SIZE_BYTES:
        raise RuntimeError(
            "Image file is too small."
        )

    with image_path.open("rb") as file:
        magic = file.read(3)

    if magic != JPEG_MAGIC_BYTES:
        raise RuntimeError(
            "Downloaded file is not a valid JPEG."
        )


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
                    "Content-Type", ""
                ).lower()
            )

            if (
                content_type
                and not content_type.startswith("image/")
            ):
                raise RuntimeError(
                    "Pexels returned a non-image "
                    "response."
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

    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def copy_reused_image(
    source: Path,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copyfile(source, destination)
    validate_jpeg_file(destination)


def create_reused_image(
    source_image: Dict[str, Any],
    destination: Path,
    index: int,
) -> Dict[str, Any]:
    source_path = (
        ROOT_DIR / source_image["file_path"]
    )

    if not source_path.exists():
        raise RuntimeError(
            "Reuse source image does not exist."
        )

    copy_reused_image(source_path, destination)

    return {
        "index": index,
        "query": (
            "reuse:" + str(source_image["query"])
        ),
        "file": f"/images/{destination.name}",
        "file_path": str(
            destination.relative_to(ROOT_DIR)
        ),
        "photographer": source_image.get(
            "photographer", ""
        ),
        "photographer_url": source_image.get(
            "photographer_url", ""
        ),
        "pexels_url": source_image.get(
            "pexels_url", ""
        ),
        "image_source_url": source_image.get(
            "image_source_url", ""
        ),
        "image_id": source_image.get("image_id"),
        "width": source_image.get("width"),
        "height": source_image.get("height"),
        "reused": True,
        "reuse_source_index": source_image.get(
            "index"
        ),
    }


def fetch_all_images(
    api_key: str,
    slug: str,
    queries: List[str],
) -> List[Dict[str, Any]]:
    if len(queries) != IMAGE_COUNT:
        raise ValueError(
            f"Exactly {IMAGE_COUNT} image "
            "queries are required."
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
        queries,
        start=1,
    ):
        print("")
        print("=" * 70)
        print(f"IMAGE {index}/{IMAGE_COUNT}")
        print(f"Query: {query}")
        print(
            "Collecting candidates from "
            "pages 1, 2 and 3 before selection..."
        )

        filename = f"{slug}-{index}.jpg"
        destination = IMAGE_DIR / filename

        try:
            candidates = collect_candidates(
                api_key,
                query,
            )

            print(
                f"Candidates collected: "
                f"{len(candidates)}"
            )

            candidate = choose_best_candidate(
                candidates,
                used_photo_ids,
                used_photographers,
            )

            if candidate is None:
                raise RuntimeError(
                    "No usable unique candidate."
                )

            print("Selected candidate:")
            print(
                f"  Photographer: "
                f"{candidate['photographer']}"
            )
            print(
                f"  Photo ID: {candidate['id']}"
            )
            print(
                f"  Page: {candidate['page']}"
            )
            print(
                f"  Aspect ratio: "
                f"{candidate['aspect_ratio']:.3f}"
            )
            print(
                f"  Area: {candidate['width']}"
                f"x{candidate['height']}"
            )
            print(
                f"  Score: "
                f"{candidate_score(candidate, used_photographers):.2f}"
            )

            download_image(
                candidate["image_url"],
                destination,
            )

            photo_id = candidate["id"]
            photographer = candidate["photographer"]

            used_photo_ids.add(photo_id)

            if photographer:
                used_photographers.add(photographer)

            images.append(
                {
                    "index": index,
                    "query": query,
                    "file": f"/images/{filename}",
                    "file_path": str(
                        destination.relative_to(
                            ROOT_DIR
                        )
                    ),
                    "photographer": photographer,
                    "photographer_url": candidate[
                        "photographer_url"
                    ],
                    "pexels_url": candidate[
                        "pexels_url"
                    ],
                    "image_source_url": candidate[
                        "image_url"
                    ],
                    "image_id": photo_id,
                    "width": candidate["width"],
                    "height": candidate["height"],
                    "aspect_ratio": candidate[
                        "aspect_ratio"
                    ],
                    "reused": False,
                }
            )

        except Exception as exc:
            failed_images += 1

            print(
                f"WARNING: image {index} failed: "
                f"{exc}",
                file=sys.stderr,
            )

            if (
                images
                and failed_images
                <= MAX_ALLOWED_FAILED_IMAGES
            ):
                source = images[
                    (failed_images - 1) % len(images)
                ]

                try:
                    reused = create_reused_image(
                        source,
                        destination,
                        index,
                    )

                    images.append(reused)

                    print(
                        f"WARNING: image {index} "
                        "was reused from a "
                        "successful image."
                    )

                except Exception as reuse_exc:
                    print(
                        f"Reuse failed: {reuse_exc}",
                        file=sys.stderr,
                    )

            if failed_images >= 4:
                raise RuntimeError(
                    "Four image failures are "
                    "considered fatal."
                )

    if len(images) != IMAGE_COUNT:
        raise RuntimeError(
            f"Expected {IMAGE_COUNT} images, "
            f"produced {len(images)}."
        )

    return images


def main() -> int:
    print("=" * 70)
    print("COMPETITIVE PEXELS FETCH")
    print("=" * 70)

    try:
        api_key = get_required_env("PEXELS_API_KEY")
        article = load_article()

        slug = str(
            article.get("slug", "")
        ).strip()

        if not slug:
            raise ValueError(
                "article.json is missing 'slug'."
            )

        raw_queries = article.get("image_queries")

        if not isinstance(raw_queries, list):
            raise ValueError(
                "article.json is missing "
                "'image_queries'."
            )

        if len(raw_queries) != IMAGE_COUNT:
            raise ValueError(
                f"Expected exactly {IMAGE_COUNT} "
                "image queries."
            )

        queries = []

        for index, query in enumerate(
            raw_queries,
            start=1,
        ):
            query = normalize_query(query)

            if not query:
                raise ValueError(
                    f"Image query #{index} "
                    "is empty."
                )

            if query.lower() in {
                item.lower() for item in queries
            }:
                raise ValueError(
                    f"Image query #{index} "
                    "is duplicated."
                )

            queries.append(query)

        images = fetch_all_images(
            api_key,
            slug,
            queries,
        )

        article["image_queries"] = queries
        article["images"] = images

        first = images[0]

        article["image"] = first["file"]
        article["image_file"] = first["file_path"]
        article["photographer"] = first["photographer"]
        article["photographer_url"] = first[
            "photographer_url"
        ]
        article["pexels_url"] = first["pexels_url"]
        article["image_source_url"] = first[
            "image_source_url"
        ]
        article["image_id"] = first["image_id"]

        save_article(article)

        print("")
        print(
            "Competitive image metadata saved."
        )
        print(f"Images saved: {len(images)}")

        for image in images:
            reused = (
                " [REUSED]"
                if image.get("reused")
                else ""
            )

            print(
                f"{image['index']}. "
                f"{image['file']} "
                f"<- {image['query']}"
                f"{reused}"
            )

        print("=" * 70)
        print(
            "COMPETITIVE PEXELS FETCH COMPLETE"
        )
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print(
            "Operation cancelled.",
            file=sys.stderr,
        )
        return 130

    except Exception as exc:
        print("", file=sys.stderr)
        print(
            "COMPETITIVE PEXELS FETCH FAILED",
            file=sys.stderr,
        )
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
