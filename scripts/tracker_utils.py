#!/usr/bin/env python3

import json

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT_DIR = Path(__file__).resolve().parents[1]
GLOBAL_TRACKER_PATH = (
    ROOT_DIR / "data" / "used_pexels_ids.json"
)

MAX_TRACKED_IDS = 5000
KEEP_TRACKED_IDS = 3000


def _normalize_tracker(
    tracker: Dict[str, Any],
) -> Dict[str, Any]:
    used_ids = tracker.get("used_ids", [])
    used_photographers = tracker.get(
        "used_photographers",
        [],
    )

    if not isinstance(used_ids, list):
        used_ids = []

    if not isinstance(used_photographers, list):
        used_photographers = []

    normalized_ids: List[Any] = []
    seen_ids = set()

    for value in used_ids:
        try:
            key = int(value)
        except (TypeError, ValueError):
            continue

        if key in seen_ids:
            continue

        seen_ids.add(key)
        normalized_ids.append(key)

    normalized_photographers: List[str] = []
    seen_photographers = set()

    for value in used_photographers:
        if not isinstance(value, str):
            continue

        photographer = value.strip()

        if not photographer:
            continue

        key = photographer.casefold()

        if key in seen_photographers:
            continue

        seen_photographers.add(key)
        normalized_photographers.append(
            photographer
        )

    return {
        "used_ids": normalized_ids,
        "used_photographers": (
            normalized_photographers
        ),
        "last_updated": str(
            tracker.get("last_updated", "") or ""
        ),
    }


def load_global_tracker() -> Dict[str, Any]:
    if not GLOBAL_TRACKER_PATH.exists():
        return {
            "used_ids": [],
            "used_photographers": [],
            "last_updated": "",
        }

    try:
        with GLOBAL_TRACKER_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            tracker = json.load(file)

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Global Pexels tracker contains "
            f"invalid JSON: {exc}"
        ) from exc

    except OSError as exc:
        raise RuntimeError(
            "Could not read global Pexels tracker: "
            f"{exc}"
        ) from exc

    if not isinstance(tracker, dict):
        raise RuntimeError(
            "Global Pexels tracker must contain "
            "a JSON object."
        )

    return _normalize_tracker(tracker)


def save_global_tracker(
    tracker: Dict[str, Any],
) -> None:
    GLOBAL_TRACKER_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    normalized = _normalize_tracker(tracker)

    normalized["last_updated"] = (
        datetime.now(timezone.utc).isoformat()
    )

    temp_path = GLOBAL_TRACKER_PATH.with_suffix(
        ".json.tmp"
    )

    try:
        with temp_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                normalized,
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")

        temp_path.replace(GLOBAL_TRACKER_PATH)

    except OSError as exc:
        temp_path.unlink(missing_ok=True)

        raise RuntimeError(
            "Could not save global Pexels tracker: "
            f"{exc}"
        ) from exc


def add_used_ids(
    tracker: Dict[str, Any],
    photo_ids: Iterable[Any],
    photographers: Iterable[str],
) -> Dict[str, Any]:
    used_ids = list(
        tracker.get("used_ids", [])
    )

    used_photographers = list(
        tracker.get("used_photographers", [])
    )

    existing_ids = set()

    for value in used_ids:
        try:
            existing_ids.add(int(value))
        except (TypeError, ValueError):
            continue

    for value in photo_ids:
        try:
            photo_id = int(value)
        except (TypeError, ValueError):
            continue

        if photo_id not in existing_ids:
            used_ids.append(photo_id)
            existing_ids.add(photo_id)

    existing_photographers = {
        value.casefold()
        for value in used_photographers
        if isinstance(value, str)
    }

    for value in photographers:
        if not isinstance(value, str):
            continue

        photographer = value.strip()

        if not photographer:
            continue

        key = photographer.casefold()

        if key not in existing_photographers:
            used_photographers.append(photographer)
            existing_photographers.add(key)

    tracker["used_ids"] = used_ids
    tracker["used_photographers"] = (
        used_photographers
    )

    cleanup_old_ids(tracker)

    return tracker


def cleanup_old_ids(
    tracker: Dict[str, Any],
) -> Dict[str, Any]:
    used_ids = tracker.get("used_ids", [])

    if not isinstance(used_ids, list):
        used_ids = []

    if len(used_ids) <= MAX_TRACKED_IDS:
        return tracker

    tracker["used_ids"] = used_ids[
        -KEEP_TRACKED_IDS:
    ]

    used_photographers = tracker.get(
        "used_photographers",
        [],
    )

    if isinstance(used_photographers, list):
        tracker["used_photographers"] = (
            used_photographers[-KEEP_TRACKED_IDS:]
        )

    return tracker
