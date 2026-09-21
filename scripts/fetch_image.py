#!/usr/bin/env python3

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"
IMAGE_DIR = ROOT_DIR / "static" / "images"

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
MAX_RETRIES = 5
REQUEST_TIMEOUT = 30


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(
            f"Required environment variable '{name}' is not set."
        )

    return value


def load_article() -> Dict[str, Any]:
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(
            f"article.json was not found: {ARTICLE_PATH}"
        )

    try:
        with ARTICLE_PATH.open("r", encoding="utf-8") as file:
            article = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid article.json: {exc}"
        ) from exc

    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain a JSON object."
        )

    return article


def save_article(article: Dict[str, Any]) -> None:
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")

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
        "per_page": 15,
        "page": page,
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                PEXELS_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code in {429, 500, 502, 503, 504}:
                delay = min(2 ** (attempt - 1), 30)

                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = min(int(retry_after), 60)
                    except ValueError:
                        pass

                print(
                    f"Pexels HTTP {response.status_code}; "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)
                continue

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise ValueError(
                    "Pexels response is not a JSON object."
                )

            return data

        except requests.RequestException as exc:
            last_error = exc

            if attempt >= MAX_RETRIES:
                break

            delay = min(2 ** (attempt - 1), 30)
            print(
                f"Pexels request failed: {exc}; "
                f"retrying in {delay}s..."
            )
            time.sleep(delay)

        except ValueError as exc:
            last_error = exc
            break

    raise RuntimeError(
        f"Pexels search failed after "
        f"{MAX_RETRIES} attempts: {last_error}"
    )


def choose_photo(
    photos: List[Dict[str, Any]],
    used_ids: set,
) -> Dict[str, Any]:
    for photo in photos:
        if not isinstance(photo, dict):
            continue

        photo_id = photo.get("id")
        if photo_id in used_ids:
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

        return {
            "id": photo_id,
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
        "No unused usable photo was found for this query."
    )


def download_image(image_url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(".tmp")

    try:
        with requests.get(
            image_url,
            stream=True,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            response.raise_for_status()

            content_type = (
                response.headers.get("Content-Type", "").lower()
            )

            if content_type and not content_type.startswith("image/"):
                raise RuntimeError(
                    "Pexels returned a non-image response: "
                    f"{content_type}"
                )

            with temp_path.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        file.write(chunk)

        if not temp_path.exists():
            raise RuntimeError(
                "Temporary image file was not created."
            )

        if temp_path.stat().st_size == 0:
            raise RuntimeError("Downloaded image file is empty.")

        temp_path.replace(destination)

    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


def main() -> int:
    try:
        print("=" * 70)
        print("Pexels image downloader — 5 images")
        print("=" * 70)

        api_key = get_required_env("PEXELS_API_KEY")
        article = load_article()

        slug = str(article.get("slug", "")).strip()
        image_queries = article.get("image_queries")

        if not slug:
            raise ValueError("article.json is missing 'slug'.")

        if not isinstance(image_queries, list):
            raise ValueError(
                "article.json must contain 'image_queries' as a list."
            )

        image_queries = [
            str(query).strip()
            for query in image_queries
            if str(query).strip()
        ]

        if len(image_queries) != 5:
            raise ValueError(
                "article.json must contain exactly 5 image_queries."
            )

        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

        images = []
        used_ids = set()

        for index, query in enumerate(image_queries, start=1):
            print("")
            print(f"[{index}/5] Searching Pexels: {query}")

            data = search_pexels(api_key, query)
            photos = data.get("photos", [])

            if not isinstance(photos, list):
                raise ValueError(
                    "Pexels returned an invalid photos list."
                )

            photo = choose_photo(photos, used_ids)
            photo_id = photo.get("id")

            if photo_id is not None:
                used_ids.add(photo_id)

            image_path = IMAGE_DIR / f"{slug}-{index}.jpg"

            download_image(photo["image_url"], image_path)

            image_url = f"/images/{slug}-{index}.jpg"

            image_info = {
                "file": image_url,
                "file_path": str(image_path.relative_to(ROOT_DIR)),
                "query": query,
                "photographer": photo["photographer"],
                "photographer_url": photo["photographer_url"],
                "pexels_url": photo["pexels_url"],
                "pexels_id": photo["id"],
            }

            images.append(image_info)

            print(f"Saved: {image_path}")
            print(f"Photographer: {photo['photographer']}")

        if len(images) != 5:
            raise RuntimeError("Exactly 5 images were required.")

        article["images"] = images
        article["image"] = images[0]["file"]
        article["image_file"] = images[0]["file_path"]
        article["photographer"] = images[0]["photographer"]
        article["photographer_url"] = images[0]["photographer_url"]
        article["pexels_url"] = images[0]["pexels_url"]

        save_article(article)

        print("")
        print("=" * 70)
        print("5 Pexels images downloaded successfully.")
        print("=" * 70)

        for index, image in enumerate(images, start=1):
            print(
                f"{index}. {image['file']} — "
                f"{image['photographer']}"
            )

        return 0

    except KeyboardInterrupt:
        print("\nOperation cancelled.", file=sys.stderr)
        return 130

    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
