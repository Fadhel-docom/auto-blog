#!/usr/bin/env python3

import json
import math
import os
import random
import re
import shutil
import sys
import time

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests

from tracker_utils import (
    add_used_ids,
    cleanup_old_ids,
    load_global_tracker,
    save_global_tracker,
)


# ============================================================================
# Configuration
# ============================================================================

ROOT_DIR = Path(__file__).resolve().parents[1]

ARTICLE_PATH = ROOT_DIR / "article.json"

IMAGE_DIR = (
    ROOT_DIR / "static" / "images"
)

PEXELS_SEARCH_URL = (
    "https://api.pexels.com/v1/search"
)

GROQ_CHAT_URL = (
    "https://api.groq.com/openai/v1/chat/completions"
)

IMAGE_COUNT = 6
MAX_PAGES = 3
PER_PAGE = 15

MIN_WIDTH = 1200
MIN_ASPECT_RATIO = 1.3
MAX_ASPECT_RATIO = 1.9
TARGET_ASPECT_RATIO = 1.5

MAX_RETRIES = 3
REQUEST_TIMEOUT = 30

MAX_ALLOWED_FAILED_IMAGES = 3

JPEG_MAGIC_BYTES = b"\xff\xd8\xff"
MIN_IMAGE_SIZE_BYTES = 1024

GLOBAL_TRACKER_PATH = (
    ROOT_DIR
    / "data"
    / "used_pexels_ids.json"
)

STYLE_MODIFIERS = [
    "minimalist",
    "scandinavian",
    "modern",
    "rustic",
    "industrial",
    "boho",
    "vintage",
    "japandi",
    "bohemian",
    "nordic",
    "coastal",
    "country",
]

RETRYABLE_STATUS_CODES = {
    429,
    500,
    502,
    503,
    504,
}

ENABLE_GROQ_VALIDATION = (
    os.getenv(
        "ENABLE_GROQ_IMAGE_VALIDATION",
        "false",
    ).lower()
    == "true"
)

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
).strip()


# ============================================================================
# Semantic dictionaries
# ============================================================================

HOME_ORGANIZATION_WHITELIST = {
    "home",
    "house",
    "interior",
    "organization",
    "organizing",
    "organized",
    "storage",
    "organizer",
    "organizers",
    "declutter",
    "decluttering",
    "tidy",
    "tidying",
    "kitchen",
    "kitchens",
    "bathroom",
    "bathrooms",
    "bedroom",
    "bedrooms",
    "closet",
    "closets",
    "wardrobe",
    "pantry",
    "pantries",
    "laundry",
    "laundries",
    "entryway",
    "entry",
    "hall",
    "hallway",
    "mudroom",
    "garage",
    "cabinet",
    "cabinets",
    "cupboard",
    "cupboards",
    "shelf",
    "shelves",
    "shelving",
    "drawer",
    "drawers",
    "rack",
    "racks",
    "bin",
    "bins",
    "basket",
    "baskets",
    "box",
    "boxes",
    "container",
    "containers",
    "hook",
    "hooks",
    "rod",
    "rods",
    "rail",
    "rails",
    "sink",
    "counter",
    "countertop",
    "vanity",
    "linen",
    "towel",
    "towels",
    "spice",
    "spices",
    "jar",
    "jars",
    "desk",
    "office",
    "workspace",
    "study",
    "nursery",
    "playroom",
    "dresser",
    "nightstand",
    "bookshelf",
    "bookcase",
    "smallspace",
    "small",
    "apartment",
    "room",
    "space",
}

STRICT_BLACKLIST = {
    "car",
    "cars",
    "automobile",
    "automobiles",
    "vehicle",
    "vehicles",
    "engine",
    "engines",
    "motor",
    "motors",
    "mechanic",
    "mechanics",
    "motorcycle",
    "motorcycles",
    "bike",
    "bikes",
    "bicycle",
    "bicycles",
    "truck",
    "trucks",
    "racecar",
    "racing",
    "food",
    "meal",
    "meals",
    "restaurant",
    "restaurants",
    "pizza",
    "burger",
    "burgers",
    "recipe",
    "recipes",
    "cooking",
    "cook",
    "dish",
    "dishes",
    "fruit",
    "vegetable",
    "vegetables",
    "portrait",
    "portraits",
    "face",
    "faces",
    "selfie",
    "selfies",
    "person",
    "people",
    "man",
    "men",
    "woman",
    "women",
    "boy",
    "boys",
    "girl",
    "girls",
    "baby",
    "babies",
    "model",
    "models",
    "animal",
    "animals",
    "cat",
    "cats",
    "dog",
    "dogs",
    "horse",
    "horses",
    "bird",
    "birds",
    "wildlife",
    "flower",
    "flowers",
    "plant",
    "plants",
    "garden",
    "gardening",
    "forest",
    "mountain",
    "mountains",
    "beach",
    "ocean",
    "sea",
    "lake",
    "river",
    "landscape",
    "nature",
    "sunset",
    "sunrise",
    "wedding",
    "party",
    "concert",
    "fashion",
    "sports",
    "football",
    "basketball",
    "soccer",
    "tennis",
    "hospital",
    "doctor",
    "medicine",
    "medical",
    "laboratory",
}

WEAK_WHITELIST_WORDS = {
    "home",
    "house",
    "room",
    "space",
    "small",
    "interior",
    "organization",
    "organized",
}


# ============================================================================
# Generic helpers
# ============================================================================

def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    value = value.lower()
    value = value.replace("-", " ")
    value = value.replace("_", " ")

    return " ".join(value.split())


def tokenize(value: Any) -> Set[str]:
    text = normalize_text(value)

    return set(
        re.findall(
            r"[a-z0-9]+",
            text,
        )
    )


def normalize_query(query: Any) -> str:
    if not isinstance(query, str):
        return ""

    return " ".join(
        query.strip().split()
    )


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
            "article.json contains invalid JSON: "
            f"{exc}"
        ) from exc

    except OSError as exc:
        raise RuntimeError(
            "Could not read article.json: "
            f"{exc}"
        ) from exc

    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain "
            "a JSON object."
        )

    return article


def save_article(
    article: Dict[str, Any],
) -> None:
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
        temp_path.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            "Could not save article.json: "
            f"{exc}"
        ) from exc


# ============================================================================
# Query diversification
# ============================================================================

def diversify_query(
    query: str,
    used_modifiers: Set[str],
) -> str:
    query = normalize_query(query)

    if not query:
        return query

    available = [
        modifier
        for modifier in STYLE_MODIFIERS
        if modifier not in used_modifiers
    ]

    if not available:
        used_modifiers.clear()
        available = STYLE_MODIFIERS.copy()

    modifier = random.choice(
        available
    )

    used_modifiers.add(modifier)

    return f"{modifier} {query}"


# ============================================================================
# Pexels search
# ============================================================================

def get_status_code(
    exception: Exception,
) -> Optional[int]:
    response = getattr(
        exception,
        "response",
        None,
    )

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
    status = (
        response.status_code
        if response is not None
        else None
    )

    # Keep the project's explicit 429 protection:
    # wait 90 seconds before retrying.
    if status == 429:
        return 90

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

    last_exception: Optional[
        Exception
    ] = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            response = requests.get(
                PEXELS_SEARCH_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 403:
                raise RuntimeError(
                    "Pexels returned HTTP 403."
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
                        f"  Pexels HTTP "
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
                raise RuntimeError(
                    "Pexels response is not "
                    "a JSON object."
                )

            return data

        except requests.Timeout as exc:
            last_exception = exc

            if attempt < MAX_RETRIES:
                delay = min(
                    2 ** (attempt - 1),
                    8,
                )

                print(
                    f"  Pexels timeout; "
                    f"retry {attempt}/"
                    f"{MAX_RETRIES} "
                    f"after {delay}s..."
                )

                time.sleep(delay)
                continue

        except requests.ConnectionError as exc:
            last_exception = exc

            if attempt < MAX_RETRIES:
                delay = min(
                    2 ** (attempt - 1),
                    8,
                )

                print(
                    f"  Pexels connection error; "
                    f"retry {attempt}/"
                    f"{MAX_RETRIES} "
                    f"after {delay}s..."
                )

                time.sleep(delay)
                continue

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
                response = getattr(
                    exc,
                    "response",
                    None,
                )

                delay = retry_delay(
                    response,
                    attempt,
                )

                print(
                    f"  Pexels request error; "
                    f"retry {attempt}/"
                    f"{MAX_RETRIES} "
                    f"after {delay}s..."
                )

                time.sleep(delay)
                continue

        except ValueError as exc:
            last_exception = exc
            break

        except RuntimeError:
            raise

    raise RuntimeError(
        "Pexels API failed after "
        f"{MAX_RETRIES} attempts: "
        f"{last_exception}"
    )


# ============================================================================
# Query fallback
# ============================================================================

def build_fallback_queries(
    query: str,
) -> List[str]:
    words = [
        word
        for word in normalize_query(
            query
        ).split()
    ]

    result: List[str] = []

    if len(words) >= 6:
        result.append(
            " ".join(words[:6])
        )

    if len(words) >= 4:
        result.append(
            " ".join(words[:4])
        )

    if len(words) >= 2:
        result.append(
            " ".join(words[:2])
        )

    result.extend(
        [
            "kitchen storage organization",
            "bathroom storage organization",
            "closet storage organization",
            "pantry storage organization",
            "cabinet storage organization",
            "drawer storage organization",
            "organized home storage",
        ]
    )

    seen = set()
    unique = []

    for item in result:
        item = normalize_query(item)

        if not item:
            continue

        key = item.lower()

        if key in seen:
            continue

        seen.add(key)
        unique.append(item)

    return unique


# ============================================================================
# Candidate extraction
# ============================================================================

def candidate_from_photo(
    photo: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    src = photo.get("src")

    if not isinstance(src, dict):
        return None

    image_url = (
        src.get("large")
        or src.get("large2x")
        or src.get("original")
    )

    if not image_url:
        return None

    photo_id = photo.get("id")

    if photo_id is None:
        return None

    try:
        width = int(
            photo.get("width") or 0
        )
        height = int(
            photo.get("height") or 0
        )
    except (TypeError, ValueError):
        return None

    if width <= 0 or height <= 0:
        return None

    aspect_ratio = width / height

    alt = str(
        photo.get("alt") or ""
    ).strip()

    pexels_url = str(
        photo.get("url") or ""
    ).strip()

    photographer = str(
        photo.get("photographer") or ""
    ).strip()

    photographer_url = str(
        photo.get("photographer_url")
        or ""
    ).strip()

    searchable_text = " ".join(
        [
            alt,
            pexels_url,
            str(
                src.get("large") or ""
            ),
            str(
                src.get("large2x") or ""
            ),
            str(
                src.get("original") or ""
            ),
        ]
    )

    return {
        "id": photo_id,
        "image_url": image_url,
        "photographer": photographer,
        "photographer_url": (
            photographer_url
        ),
        "pexels_url": pexels_url,
        "alt": alt,
        "searchable_text": normalize_text(
            searchable_text
        ),
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
    }


# ============================================================================
# Semantic validation
# ============================================================================

def is_query_match(
    query: str,
    candidate: Dict[str, Any],
) -> bool:
    query_tokens = tokenize(query)

    meaningful_query_tokens = {
        token
        for token in query_tokens
        if token not in WEAK_WHITELIST_WORDS
        and len(token) >= 3
    }

    if not meaningful_query_tokens:
        return False

    candidate_tokens = tokenize(
        candidate.get(
            "searchable_text",
            "",
        )
    )

    direct_matches = (
        meaningful_query_tokens
        & candidate_tokens
    )

    return bool(direct_matches)


def is_dimension_ok(
    candidate: Dict[str, Any],
) -> bool:
    width = int(
        candidate.get("width", 0)
        or 0
    )

    height = int(
        candidate.get("height", 0)
        or 0
    )

    ratio = float(
        candidate.get(
            "aspect_ratio",
            0,
        )
        or 0
    )

    if width < MIN_WIDTH:
        return False

    if height <= 0:
        return False

    if ratio < MIN_ASPECT_RATIO:
        return False

    if ratio > MAX_ASPECT_RATIO:
        return False

    if ratio > 2.0:
        return False

    return True


def blacklist_matches(
    query: str,
    candidate: Dict[str, Any],
) -> Set[str]:
    query_tokens = tokenize(query)

    candidate_tokens = tokenize(
        candidate.get(
            "searchable_text",
            "",
        )
    )

    allowed_blacklist_terms = (
        query_tokens & STRICT_BLACKLIST
    )

    return {
        word
        for word in (
            candidate_tokens
            & STRICT_BLACKLIST
        )
        if word
        not in allowed_blacklist_terms
    }


def whitelist_matches(
    candidate: Dict[str, Any],
) -> Set[str]:
    candidate_tokens = tokenize(
        candidate.get(
            "searchable_text",
            "",
        )
    )

    return (
        candidate_tokens
        & HOME_ORGANIZATION_WHITELIST
    )


def is_content_acceptable(
    candidate: Dict[str, Any],
    query: str,
) -> bool:
    blacklist = blacklist_matches(
        query,
        candidate,
    )

    if blacklist:
        return False

    if is_query_match(
        query,
        candidate,
    ):
        return True

    matches = whitelist_matches(
        candidate
    )

    meaningful_matches = {
        word
        for word in matches
        if word not in WEAK_WHITELIST_WORDS
    }

    return len(
        meaningful_matches
    ) >= 2


# ============================================================================
# Candidate collection
# ============================================================================

def collect_candidates(
    api_key: str,
    query: str,
    search_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    semantic_query = normalize_query(
        query
    )

    actual_search_query = (
        normalize_query(search_query)
        if search_query
        else semantic_query
    )

    print(
        '  Searching Pexels query: '
        f'"{actual_search_query}"'
    )

    candidates: List[
        Dict[str, Any]
    ] = []

    seen_ids: Set[Any] = set()

    queries = [
        actual_search_query
    ]

    for fallback in build_fallback_queries(
        semantic_query
    ):
        if (
            fallback.lower()
            != actual_search_query.lower()
        ):
            queries.append(fallback)

    dimension_count = 0
    semantic_count = 0
    blacklist_count = 0

    for query_index, current_query in enumerate(
        queries
    ):
        if query_index > 0:
            print(
                '  Trying fallback query: '
                f'"{current_query}"'
            )

        for page in range(
            1,
            MAX_PAGES + 1,
        ):
            print(
                f"  Searching page "
                f"{page}/{MAX_PAGES}..."
            )

            try:
                data = search_pexels(
                    api_key,
                    current_query,
                    page,
                )

            except RuntimeError as exc:
                print(
                    "  WARNING: search failed: "
                    f"{exc}",
                    file=sys.stderr,
                )
                break

            photos = data.get(
                "photos",
                [],
            )

            if not isinstance(
                photos,
                list,
            ):
                continue

            print(
                f"  Candidates found: "
                f"{len(photos)}"
            )

            for photo in photos:
                if not isinstance(
                    photo,
                    dict,
                ):
                    continue

                candidate = (
                    candidate_from_photo(
                        photo
                    )
                )

                if candidate is None:
                    continue

                photo_id = candidate["id"]

                if photo_id in seen_ids:
                    continue

                seen_ids.add(photo_id)

                if not is_dimension_ok(
                    candidate
                ):
                    print(
                        f"  Rejected candidate "
                        f"#{photo_id}: "
                        "aspect/dimensions "
                        f"{candidate['width']}x"
                        f"{candidate['height']} "
                        f"ratio="
                        f"{candidate['aspect_ratio']:.2f}"
                    )
                    continue

                dimension_count += 1

                blacklist = (
                    blacklist_matches(
                        semantic_query,
                        candidate,
                    )
                )

                if blacklist:
                    word = sorted(
                        blacklist
                    )[0]

                    blacklist_count += 1

                    print(
                        f"  Rejected candidate "
                        f"#{photo_id}: "
                        f'blacklist "{word}"'
                    )
                    continue

                query_match = (
                    is_query_match(
                        semantic_query,
                        candidate,
                    )
                )

                home_matches = (
                    whitelist_matches(
                        candidate
                    )
                )

                meaningful_home_matches = {
                    word
                    for word in home_matches
                    if word
                    not in WEAK_WHITELIST_WORDS
                }

                if not (
                    query_match
                    or len(
                        meaningful_home_matches
                    )
                    >= 2
                ):
                    print(
                        f"  Rejected candidate "
                        f"#{photo_id}: "
                        "no semantic match"
                    )
                    continue

                semantic_count += 1

                candidate[
                    "matched_query"
                ] = current_query

                candidate[
                    "semantic_query"
                ] = semantic_query

                candidate["page"] = page

                candidate[
                    "query_match"
                ] = query_match

                candidate[
                    "whitelist_matches"
                ] = sorted(
                    meaningful_home_matches
                )

                candidate[
                    "blacklist_matches"
                ] = []

                candidates.append(
                    candidate
                )

            if (
                query_index == 0
                and len(candidates) >= 5
            ):
                break

    print(
        "  After dimension filter: "
        f"{dimension_count}"
    )

    print(
        "  After semantic filter: "
        f"{semantic_count}"
    )

    print(
        "  After blacklist filter: "
        f"{blacklist_count}"
    )

    print(
        "  Final candidates: "
        f"{len(candidates)}"
    )

    return candidates


# ============================================================================
# Candidate scoring
# ============================================================================

def score_candidate(
    candidate: Dict[str, Any],
    used_photographers: Set[str],
) -> float:
    ratio = float(
        candidate.get(
            "aspect_ratio",
            0,
        )
        or 0
    )

    width = int(
        candidate.get("width", 0)
        or 0
    )

    height = int(
        candidate.get("height", 0)
        or 0
    )

    area = max(
        1,
        width * height,
    )

    ratio_difference = abs(
        ratio - TARGET_ASPECT_RATIO
    )

    aspect_score = max(
        0.0,
        35.0
        - (
            ratio_difference
            * 35.0
        ),
    )

    resolution_score = min(
        20.0,
        math.log10(area) * 2.0,
    )

    query_score = (
        25.0
        if candidate.get(
            "query_match"
        )
        else 12.0
    )

    photographer = str(
        candidate.get(
            "photographer",
            "",
        )
    ).strip()

    photographer_score = (
        15.0
        if photographer
        and photographer
        not in used_photographers
        else 0.0
    )

    page = int(
        candidate.get(
            "page",
            3,
        )
        or 3
    )

    page_score = max(
        0.0,
        5.0 - page,
    )

    return (
        aspect_score
        + resolution_score
        + query_score
        + photographer_score
        + page_score
    )


def choose_best_candidate(
    candidates: List[Dict[str, Any]],
    used_ids: Set[Any],
    used_photographers: Set[str],
) -> Optional[Dict[str, Any]]:
    filtered: List[
        Dict[str, Any]
    ] = []

    for candidate in candidates:
        if candidate["id"] in used_ids:
            print(
                "  Rejected candidate "
                f"#{candidate['id']}: "
                "already used"
            )
            continue

        filtered.append(candidate)

    if not filtered:
        return None

    unique_photographers = [
        candidate
        for candidate in filtered
        if candidate.get(
            "photographer",
            "",
        )
        not in used_photographers
    ]

    if unique_photographers:
        filtered = (
            unique_photographers
        )

    for candidate in filtered:
        candidate[
            "validation_score"
        ] = score_candidate(
            candidate,
            used_photographers,
        )

    filtered.sort(
        key=lambda item: (
            item["validation_score"],
            item.get("width", 0)
            * item.get("height", 0),
        ),
        reverse=True,
    )

    return filtered[0]


# ============================================================================
# H2 extraction
# ============================================================================

def extract_h2_headings(
    article: Dict[str, Any],
) -> List[str]:
    possible_content = []

    for key in (
        "content",
        "content_markdown",
        "body",
        "markdown",
    ):
        value = article.get(key)

        if isinstance(value, str):
            possible_content.append(value)

    headings: List[str] = []

    for content in possible_content:
        in_code_block = False

        for line in content.splitlines():
            stripped = line.strip()

            if stripped.startswith(
                "```"
            ):
                in_code_block = (
                    not in_code_block
                )
                continue

            if in_code_block:
                continue

            match = re.match(
                r"^##\s+(.+?)\s*$",
                line,
            )

            if match:
                heading = (
                    match.group(1)
                    .strip()
                )

                if heading:
                    headings.append(
                        heading
                    )

        if headings:
            break

    return headings


def get_h2_for_image(
    article: Dict[str, Any],
    index: int,
) -> str:
    headings = extract_h2_headings(
        article
    )

    if not headings:
        return ""

    if index == 1:
        return str(
            article.get(
                "title",
                headings[0],
            )
            or headings[0]
        ).strip()

    heading_index = index - 2

    if (
        0
        <= heading_index
        < len(headings)
    ):
        return headings[
            heading_index
        ]

    return headings[-1]


# ============================================================================
# Optional Groq validation
# ============================================================================

def groq_validate_image(
    api_key: str,
    candidate: Dict[str, Any],
    h2_heading: str,
) -> bool:
    if not ENABLE_GROQ_VALIDATION:
        return True

    if not api_key:
        print(
            "  Groq validation requested "
            "but GROQ_API_KEY is missing."
        )
        return False

    alt = str(
        candidate.get(
            "alt",
            "",
        )
    ).strip()

    matched_query = str(
        candidate.get(
            "matched_query",
            "",
        )
    ).strip()

    prompt = f"""
You are a strict image relevance validator.

Article section: {h2_heading}
Search query: {matched_query}
Pexels image description: {alt}

Determine whether this image is clearly relevant
to the article section and suitable for a Home
Organization article.

Reject:
- cars
- engines
- vehicles
- unrelated people
- portraits
- food
- animals
- nature
- unrelated interiors
- generic unrelated stock photos

Accept only when the image clearly matches
the subject.

Reply with exactly: YES or NO
""".strip()

    headers = {
        "Authorization": (
            f"Bearer {api_key}"
        ),
        "Content-Type": (
            "application/json"
        ),
    }

    payload = {
        "model": GROQ_MODEL,
        "temperature": 0,
        "max_tokens": 5,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return exactly YES "
                    "or NO. Be conservative."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }

    try:
        response = requests.post(
            GROQ_CHAT_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        choices = data.get(
            "choices",
            [],
        )

        if not choices:
            print(
                "  Groq validation: NO "
                "(no response)"
            )
            return False

        content = str(
            choices[0]
            .get("message", {})
            .get("content", "")
        ).strip().upper()

        if content == "YES":
            print(
                "  Groq validation: YES "
                f'(matches "{h2_heading}")'
            )
            return True

        print(
            "  Groq validation: NO "
            f"(response={content!r})"
        )

        return False

    except Exception as exc:
        print(
            f"  Groq validation ERROR: "
            f"{exc}"
        )
        return False


# ============================================================================
# JPEG validation
# ============================================================================

def validate_jpeg_file(
    path: Path,
) -> None:
    if not path.exists():
        raise RuntimeError(
            "Image file was not created."
        )

    size = path.stat().st_size

    if size <= MIN_IMAGE_SIZE_BYTES:
        raise RuntimeError(
            "Image file is too small: "
            f"{size} bytes."
        )

    with path.open("rb") as file:
        magic = file.read(3)

    if magic != JPEG_MAGIC_BYTES:
        raise RuntimeError(
            "Downloaded file is not "
            "a valid JPEG."
        )


def download_image(
    url: str,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = destination.with_suffix(
        ".tmp"
    )

    try:
        with requests.get(
            url,
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
                    "Pexels returned a "
                    "non-image "
                    "Content-Type: "
                    f"{content_type}"
                )

            with temp_path.open(
                "wb"
            ) as file:
                for chunk in (
                    response.iter_content(
                        chunk_size=64 * 1024
                    )
                ):
                    if chunk:
                        file.write(chunk)

        validate_jpeg_file(
            temp_path
        )

        temp_path.replace(
            destination
        )

        validate_jpeg_file(
            destination
        )

    except Exception:
        temp_path.unlink(
            missing_ok=True
        )
        raise


# ============================================================================
# Reuse fallback
# ============================================================================

def copy_reused_image(
    source: Path,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copyfile(
        source,
        destination,
    )

    validate_jpeg_file(
        destination
    )


def create_reused_image(
    source_image: Dict[str, Any],
    destination: Path,
    index: int,
) -> Dict[str, Any]:
    source_path = (
        ROOT_DIR
        / source_image["file_path"]
    )

    if not source_path.exists():
        raise RuntimeError(
            "Reuse source image does "
            "not exist."
        )

    copy_reused_image(
        source_path,
        destination,
    )

    return {
        "index": index,
        "query": (
            "reuse:"
            + str(
                source_image.get(
                    "query",
                    "",
                )
            )
        ),
        "file": (
            f"/images/"
            f"{destination.name}"
        ),
        "file_path": str(
            destination.relative_to(
                ROOT_DIR
            )
        ),
        "photographer": (
            source_image.get(
                "photographer",
                "",
            )
        ),
        "photographer_url": (
            source_image.get(
                "photographer_url",
                "",
            )
        ),
        "pexels_url": (
            source_image.get(
                "pexels_url",
                "",
            )
        ),
        "image_source_url": (
            source_image.get(
                "image_source_url",
                "",
            )
        ),
        "image_id": source_image.get(
            "image_id"
        ),
        "width": source_image.get(
            "width"
        ),
        "height": source_image.get(
            "height"
        ),
        "aspect_ratio": source_image.get(
            "aspect_ratio"
        ),
        "reused": True,
        "validation_score": float(
            source_image.get(
                "validation_score",
                0,
            )
            or 0
        ),
        "groq_validated": bool(
            source_image.get(
                "groq_validated",
                False,
            )
        ),
        "reuse_source_index": (
            source_image.get(
                "index"
            )
        ),
    }


# ============================================================================
# Main image pipeline
# ============================================================================

def fetch_all_images(
    api_key: str,
    slug: str,
    queries: List[str],
) -> List[Dict[str, Any]]:
    if len(queries) != IMAGE_COUNT:
        raise ValueError(
            f"Exactly {IMAGE_COUNT} "
            "image queries are required."
        )

    IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    groq_api_key = os.getenv(
        "GROQ_API_KEY",
        "",
    ).strip()

    global_tracker = (
        load_global_tracker()
    )

    cleanup_old_ids(
        global_tracker
    )

    global_used_ids = set(
        global_tracker.get(
            "used_ids",
            [],
        )
    )

    global_used_photographers = set(
        global_tracker.get(
            "used_photographers",
            [],
        )
    )

    print(
        "Global tracker: "
        f"{len(global_used_ids)} "
        "photo IDs"
    )

    print(
        "Global photographer tracker: "
        f"{len(global_used_photographers)} "
        "photographers"
    )

    images: List[
        Dict[str, Any]
    ] = []

    # Global history + current article.
    used_ids: Set[Any] = set(
        global_used_ids
    )

    used_photographers: Set[str] = set(
        global_used_photographers
    )

    failed_images = 0

    used_modifiers: Set[str] = set()

    for index, query in enumerate(
        queries,
        start=1,
    ):
        print("")
        print("=" * 70)
        print(
            f"IMAGE {index}/{IMAGE_COUNT}"
        )
        print(
            f'Original query: "{query}"'
        )

        article = load_article()

        h2_heading = (
            get_h2_for_image(
                article,
                index,
            )
        )

        if h2_heading:
            print(
                f"Section: {h2_heading}"
            )

        filename = (
            f"{slug}-{index}.jpg"
        )

        destination = (
            IMAGE_DIR / filename
        )

        try:
            diversified_query = (
                diversify_query(
                    query,
                    used_modifiers,
                )
            )

            print(
                "Diversified Pexels query: "
                f'"{diversified_query}"'
            )

            candidates = (
                collect_candidates(
                    api_key,
                    query,
                    diversified_query,
                )
            )

            candidate = (
                choose_best_candidate(
                    candidates,
                    used_ids,
                    used_photographers,
                )
            )

            if candidate is None:
                raise RuntimeError(
                    "No acceptable globally "
                    "unique image candidate "
                    "was found."
                )

            candidates.sort(
                key=lambda item: (
                    score_candidate(
                        item,
                        used_photographers,
                    ),
                ),
                reverse=True,
            )

            selected = None

            for ranked_candidate in candidates:
                if (
                    ranked_candidate["id"]
                    in used_ids
                ):
                    continue

                if ENABLE_GROQ_VALIDATION:
                    if not groq_validate_image(
                        groq_api_key,
                        ranked_candidate,
                        h2_heading,
                    ):
                        print(
                            "  Rejected candidate "
                            f"#{ranked_candidate['id']} "
                            "by Groq."
                        )
                        continue

                    ranked_candidate[
                        "groq_validated"
                    ] = True

                else:
                    ranked_candidate[
                        "groq_validated"
                    ] = False

                selected = (
                    ranked_candidate
                )
                break

            if selected is None:
                raise RuntimeError(
                    "All semantically valid "
                    "globally unique candidates "
                    "were rejected by Groq."
                )

            candidate = selected

            validation_score = (
                score_candidate(
                    candidate,
                    used_photographers,
                )
            )

            print(
                "Selected: Photo ID "
                f"{candidate['id']} "
                "(photographer "
                f"{candidate['photographer']}, "
                f"{candidate['aspect_ratio']:.2f} "
                "ratio, page "
                f"{candidate['page']})"
            )

            print(
                "Validation score: "
                f"{validation_score:.2f}"
            )

            print(
                "Image dimensions: "
                f"{candidate['width']}x"
                f"{candidate['height']}"
            )

            if candidate.get("alt"):
                print(
                    f"Alt: {candidate['alt']}"
                )

            download_image(
                candidate["image_url"],
                destination,
            )

            print(
                "Downloaded successfully."
            )

            photo_id = candidate["id"]

            photographer = candidate.get(
                "photographer",
                "",
            )

            used_ids.add(photo_id)

            if photographer:
                used_photographers.add(
                    photographer
                )

            images.append(
                {
                    "index": index,
                    "query": query,
                    "file": (
                        f"/images/"
                        f"{filename}"
                    ),
                    "file_path": str(
                        destination.relative_to(
                            ROOT_DIR
                        )
                    ),
                    "photographer": (
                        photographer
                    ),
                    "photographer_url": (
                        candidate.get(
                            "photographer_url",
                            "",
                        )
                    ),
                    "pexels_url": (
                        candidate.get(
                            "pexels_url",
                            "",
                        )
                    ),
                    "image_source_url": (
                        candidate.get(
                            "image_url",
                            "",
                        )
                    ),
                    "image_id": photo_id,
                    "width": candidate[
                        "width"
                    ],
                    "height": candidate[
                        "height"
                    ],
                    "aspect_ratio": (
                        candidate[
                            "aspect_ratio"
                        ]
                    ),
                    "reused": False,
                    "validation_score": round(
                        validation_score,
                        2,
                    ),
                    "groq_validated": bool(
                        candidate.get(
                            "groq_validated",
                            False,
                        )
                    ),
                }
            )

        except Exception as exc:
            failed_images += 1

            print(
                f"WARNING: image {index} "
                f"failed: {exc}",
                file=sys.stderr,
            )

            if (
                images
                and failed_images
                <= MAX_ALLOWED_FAILED_IMAGES
            ):
                source = images[
                    (
                        failed_images - 1
                    )
                    % len(images)
                ]

                try:
                    reused = (
                        create_reused_image(
                            source,
                            destination,
                            index,
                        )
                    )

                    images.append(
                        reused
                    )

                    print(
                        f"WARNING: image {index} "
                        "was reused from a "
                        "previous successful image."
                    )

                except Exception as reuse_exc:
                    print(
                        "ERROR: reuse failed: "
                        f"{reuse_exc}",
                        file=sys.stderr,
                    )

            if failed_images >= 4:
                raise RuntimeError(
                    "Four image failures "
                    "are considered fatal."
                )

    if len(images) != IMAGE_COUNT:
        raise RuntimeError(
            f"Expected {IMAGE_COUNT} "
            f"images, produced "
            f"{len(images)}."
        )

    if failed_images:
        print("")
        print(
            f"WARNING: {failed_images} "
            "image(s) required controlled "
            "fallback/reuse."
        )

    # Only genuinely downloaded Pexels images
    # enter the permanent global tracker.
    new_photo_ids = [
        image["image_id"]
        for image in images
        if (
            not image.get("reused")
            and image.get("image_id")
            is not None
        )
    ]

    new_photographers = [
        image.get(
            "photographer",
            "",
        )
        for image in images
        if (
            not image.get("reused")
            and image.get(
                "photographer",
                "",
            )
        )
    ]

    add_used_ids(
        global_tracker,
        new_photo_ids,
        new_photographers,
    )

    cleanup_old_ids(
        global_tracker
    )

    save_global_tracker(
        global_tracker
    )

    print("")
    print(
        "Global Pexels tracker updated."
    )

    print(
        "Tracked photo IDs: "
        f"{len(global_tracker['used_ids'])}"
    )

    print(
        "Tracked photographers: "
        f"{len(global_tracker['used_photographers'])}"
    )

    return images


# ============================================================================
# Entry point
# ============================================================================

def main() -> int:
    print("=" * 70)
    print(
        "COMPETITIVE PEXELS FETCH"
    )
    print("=" * 70)

    try:
        api_key = get_required_env(
            "PEXELS_API_KEY"
        )

        article = load_article()

        slug = str(
            article.get(
                "slug",
                "",
            )
        ).strip()

        if not slug:
            raise ValueError(
                "article.json is missing "
                "'slug'."
            )

        raw_queries = article.get(
            "image_queries"
        )

        if not isinstance(
            raw_queries,
            list,
        ):
            raise ValueError(
                "article.json is missing "
                "'image_queries'."
            )

        if len(raw_queries) != IMAGE_COUNT:
            raise ValueError(
                f"Expected exactly "
                f"{IMAGE_COUNT} "
                "image queries."
            )

        queries: List[str] = []

        seen_queries: Set[str] = set()

        for index, raw_query in enumerate(
            raw_queries,
            start=1,
        ):
            query = normalize_query(
                raw_query
            )

            if not query:
                raise ValueError(
                    f"Image query #{index} "
                    "is empty."
                )

            key = query.lower()

            if key in seen_queries:
                raise ValueError(
                    f"Image query #{index} "
                    "is duplicated."
                )

            seen_queries.add(key)
            queries.append(query)

        print(
            f"Images requested: "
            f"{IMAGE_COUNT}"
        )

        print(
            f"Pages per query: "
            f"{MAX_PAGES}"
        )

        print(
            f"Results per page: "
            f"{PER_PAGE}"
        )

        print(
            f"Minimum width: "
            f"{MIN_WIDTH}px"
        )

        print(
            "Aspect ratio: "
            f"{MIN_ASPECT_RATIO:.2f} - "
            f"{MAX_ASPECT_RATIO:.2f}"
        )

        print(
            "Semantic whitelist: ENABLED"
        )

        print(
            "Strict blacklist: ENABLED"
        )

        print(
            "Global duplicate tracker: "
            "ENABLED"
        )

        print(
            "Query diversification: "
            "ENABLED"
        )

        print(
            "Groq validation: "
            + (
                "ENABLED"
                if ENABLE_GROQ_VALIDATION
                else "DISABLED"
            )
        )

        images = fetch_all_images(
            api_key,
            slug,
            queries,
        )

        article[
            "image_queries"
        ] = queries

        article["images"] = images

        hero = images[0]

        article["image"] = (
            hero["file"]
        )

        article["image_file"] = (
            hero["file_path"]
        )

        article["photographer"] = (
            hero["photographer"]
        )

        article["photographer_url"] = (
            hero["photographer_url"]
        )

        article["pexels_url"] = (
            hero["pexels_url"]
        )

        article["image_source_url"] = (
            hero["image_source_url"]
        )

        article["image_id"] = (
            hero["image_id"]
        )

        article["image_alt"] = (
            hero.get("alt", "")
        )

        save_article(article)

        print("")
        print("=" * 70)
        print(
            "COMPETITIVE PEXELS "
            "FETCH COMPLETE"
        )

        print(
            f"Images saved: "
            f"{len(images)}"
        )

        print("=" * 70)

        for image in images:
            marker = (
                " [REUSED]"
                if image.get("reused")
                else ""
            )

            print(
                f"{image['index']}. "
                f"{image['file']} "
                f"<- {image['query']}"
                f"{marker}"
            )

        return 0

    except KeyboardInterrupt:
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
            "COMPETITIVE PEXELS "
            "FETCH FAILED",
            file=sys.stderr,
        )

        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
