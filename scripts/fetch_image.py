#!/usr/bin/env python3

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"
IMAGE_DIR = ROOT_DIR / "static" / "images"

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"

MAX_RETRIES = 5
REQUEST_TIMEOUT = 30
IMAGE_COUNT = 5


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

        temp_path.replace(ARTICLE_PATH)

    except OSError as exc:
        raise RuntimeError(
            f"Could not save article.json: {exc}"
        ) from exc


def get_status_code(exception: Exception) -> Optional[int]:
    response = getattr(exception, "response", None)

    if response is not None:
        status_code = getattr(response, "status_code", None)

        if status_code is not None:
            return status_code

    return None


def get_retry_delay(
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

    return min(2 ** (attempt - 1), 30)


def search_pexels(
    api_key: str,
    query: str,
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
        "page": 1,
    }

    session = requests.Session()

    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                PEXELS_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code in {
                429,
                500,
                502,
                503,
                504,
            }:
                delay = get_retry_delay(response, attempt)

                print(
                    f"Pexels returned HTTP "
                    f"{response.status_code}. "
                    f"Retry {attempt}/{MAX_RETRIES} "
                    f"after {delay} seconds..."
                )

                time.sleep(delay)
                continue

            response.raise_for_status()

            try:
                return response.json()

            except ValueError as exc:
                raise RuntimeError(
                    "Pexels returned invalid JSON."
                ) from exc

        except requests.RequestException as exc:
            last_error = exc

            status_code = get_status_code(exc)

            if status_code not in {
                429,
                500,
                502,
                503,
                504,
                None,
            }:
                raise RuntimeError(
                    f"Pexels API request failed "
                    f"with HTTP {status_code}: {exc}"
                ) from exc

            if attempt < MAX_RETRIES:
                delay = min(2 ** (attempt - 1), 30)

                print(
                    f"Pexels request failed: {exc}. "
                    f"Retry {attempt}/{MAX_RETRIES} "
                    f"after {delay} seconds..."
                )

                time.sleep(delay)

    raise RuntimeError(
        f"Pexels API failed after "
        f"{MAX_RETRIES} attempts: {last_error}"
    )


def choose_photo(data: Dict[str, Any]) -> Dict[str, Any]:
    photos = data.get("photos")

    if not isinstance(photos, list):
        raise ValueError(
            "Pexels response does not contain "
            "a valid 'photos' list."
        )

    if not photos:
        raise ValueError(
            "Pexels returned no photos "
            "for the requested image query."
        )

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

        if image_url:
            return {
                "id": photo.get("id"),
                "image_url": image_url,
                "photographer": (
                    photo.get("photographer")
                    or "Unknown photographer"
                ),
                "photographer_url": (
                    photo.get("photographer_url") or ""
                ),
                "pexels_url": photo.get("url") or "",
                "width": photo.get("width"),
                "height": photo.get("height"),
            }

    raise ValueError(
        "Pexels returned photos, but none "
        "contained a usable image URL."
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
                    "Content-Type",
                    "",
                ).lower()
            )

            if (
                content_type
                and not content_type.startswith("image/")
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

        if not temp_path.exists():
            raise RuntimeError(
                "Temporary image file was not created."
            )

        if temp_path.stat().st_size == 0:
            raise RuntimeError(
                "Downloaded image file is empty."
            )

        temp_path.replace(destination)

    except requests.RequestException as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

        raise RuntimeError(
            f"Could not download image from Pexels: {exc}"
        ) from exc

    except OSError as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

        raise RuntimeError(
            f"Could not save downloaded image: {exc}"
        ) from exc


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

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    images = []

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

        data = search_pexels(api_key, query)
        photo = choose_photo(data)

        image_url = photo["image_url"]
        photographer = photo["photographer"]
        photographer_url = photo["photographer_url"]
        pexels_url = photo["pexels_url"]

        filename = f"{slug}-{index}.jpg"
        image_path = IMAGE_DIR / filename

        print(f"Selected photographer: {photographer}")
        print(f"Image URL: {image_url}")
        print(f"Destination: {image_path}")

        download_image(image_url, image_path)

        images.append(
            {
                "index": index,
                "query": query,
                "file": f"/images/{filename}",
                "file_path": str(
                    image_path.relative_to(ROOT_DIR)
                ),
                "photographer": photographer,
                "photographer_url": photographer_url,
                "pexels_url": pexels_url,
                "image_source_url": image_url,
                "image_id": photo.get("id"),
                "width": photo.get("width"),
                "height": photo.get("height"),
            }
        )

    print("")
    print("=" * 70)
    print("All 5 images downloaded successfully.")
    print("=" * 70)

    return images


def main() -> int:
    try:
        print("=" * 70)
        print("Pexels image downloader")
        print("=" * 70)

        api_key = get_required_env("PEXELS_API_KEY")

        article = load_article()

        slug = article.get("slug")
        image_queries = article.get("image_queries")

        if not isinstance(slug, str) or not slug.strip():
            raise ValueError(
                "article.json is missing "
                "a valid 'slug'."
            )

        if not isinstance(image_queries, list):
            raise ValueError(
                "article.json is missing "
                "the 'image_queries' array."
            )

        if len(image_queries) != IMAGE_COUNT:
            raise ValueError(
                f"article.json must contain exactly "
                f"{IMAGE_COUNT} image queries."
            )

        slug = slug.strip()

        normalized_queries = []

        for index, query in enumerate(
            image_queries,
            start=1,
        ):
            if not isinstance(query, str):
                raise ValueError(
                    f"Image query {index} must be a string."
                )

            query = query.strip()

            if not query:
                raise ValueError(
                    f"Image query {index} is empty."
                )

            if query not in normalized_queries:
                normalized_queries.append(query)

        if len(normalized_queries) != IMAGE_COUNT:
            raise ValueError(
                "Image queries must be unique."
            )

        images = download_all_images(
            api_key,
            slug,
            normalized_queries,
        )

        article["image_queries"] = normalized_queries
        article["images"] = images
        article["image"] = images[0]["file"]
        article["image_file"] = images[0]["file_path"]
        article["photographer"] = images[0]["photographer"]
        article["photographer_url"] = images[0]["photographer_url"]
        article["pexels_url"] = images[0]["pexels_url"]
        article["image_source_url"] = images[0]["image_source_url"]
        article["image_id"] = images[0]["image_id"]

        save_article(article)

        print("")
        print("=" * 70)
        print("Image metadata saved successfully.")
        print(f"Article JSON: {ARTICLE_PATH}")

        for image in images:
            print(
                f"{image['index']}. "
                f"{image['file']} "
                f"← {image['query']}"
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
