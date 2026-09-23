"""
category_utils.py — P0-2

Unified category detection for auto-blog.

Maps each article to exactly ONE category from the
canonical set:

    Kitchen
    Bathroom
    Bedroom
    Small Space
    Decluttering
    Rental

Detection uses keyword + title + tags, in that order
of specificity.
"""

from __future__ import annotations

from typing import Iterable


CANONICAL_CATEGORIES = (
    "Kitchen",
    "Bathroom",
    "Bedroom",
    "Small Space",
    "Decluttering",
    "Rental",
)


# ---------------------------------------------------------------------------
# Rules — checked in order.
# The FIRST match wins.
# ---------------------------------------------------------------------------
_RULES = (
    (
        "Rental",
        (
            "renter",
            "rental",
            "renting",
            "no drill",
            "no-drill",
            "drill free",
            "drill-free",
            "damage free",
            "damage-free",
            "removable",
            "temporary",
        ),
    ),
    (
        "Kitchen",
        (
            "kitchen",
            "pantry",
            "spice",
            "countertop",
            "cabinet",
            "cabinets",
            "fridge",
            "refrigerator",
            "galley",
            "utensil",
            "dish",
        ),
    ),
    (
        "Bathroom",
        (
            "bathroom",
            "bath",
            "shower",
            "sink",
            "toilet",
            "vanity",
            "powder room",
            "toiletries",
            "towel",
            "tension rod",
        ),
    ),
    (
        "Bedroom",
        (
            "bedroom",
            "bed",
            "closet",
            "wardrobe",
            "dresser",
            "nightstand",
            "under bed",
            "under-bed",
            "underbed",
        ),
    ),
    (
        "Decluttering",
        (
            "declutter",
            "decluttering",
            "minimalist",
            "minimalism",
            "clutter",
            "purge",
            "konmari",
        ),
    ),
    (
        "Small Space",
        (
            "small space",
            "small-space",
            "small apartment",
            "studio",
            "tiny",
            "compact",
            "micro",
            "5x5",
            "3ft",
            "3 ft",
        ),
    ),
)


def detect_category(
    keyword: str = "",
    title: str = "",
    tags: Iterable[str] | None = None,
) -> str:
    """
    Return exactly ONE canonical category.

    Priority:
        1. keyword (most specific signal)
        2. title
        3. tags
        4. fallback: "Small Space"
    """
    tags_list = list(tags or [])

    keyword_text = str(keyword or "").lower()
    title_text = str(title or "").lower()
    tags_text = " ".join(
        str(t).lower() for t in tags_list
    )

    # Check keyword first
    for category, needles in _RULES:
        for needle in needles:
            if needle in keyword_text:
                return category

    # Then title
    for category, needles in _RULES:
        for needle in needles:
            if needle in title_text:
                return category

    # Then tags
    for category, needles in _RULES:
        for needle in needles:
            if needle in tags_text:
                return category

    # Fallback
    return "Small Space"


def is_canonical(category: str) -> bool:
    return category in CANONICAL_CATEGORIES


# ---------------------------------------------------------------------------
# Self-test — run: python scripts/category_utils.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cases = [
        (
            "small bathroom organization ideas",
            "Small Bathroom Organization Ideas",
            [],
            "Bathroom",
        ),
        (
            "small kitchen organization ideas",
            "Small Kitchen Organization Ideas",
            [],
            "Kitchen",
        ),
        (
            "renter friendly kitchen organization",
            "Renter Friendly Kitchen Organization",
            [],
            "Rental",
        ),
        (
            "small bedroom storage ideas",
            "Small Bedroom Storage Ideas",
            [],
            "Bedroom",
        ),
        (
            "decluttering a 5x5 home office corner",
            "Decluttering a 5x5 Home Office Corner",
            [],
            "Decluttering",
        ),
        (
            "small space organization",
            "Small Space Organization",
            [],
            "Small Space",
        ),
    ]

    ok = True

    for keyword, title, tags, expected in cases:
        got = detect_category(
            keyword=keyword,
            title=title,
            tags=tags,
        )
        mark = "[OK]" if got == expected else "[FAIL]"

        if got != expected:
            ok = False

        print(f"{mark} {keyword!r}")
        print(f"   expected: {expected}")
        print(f"   got     : {got}")
        print("")

    raise SystemExit(0 if ok else 1)
