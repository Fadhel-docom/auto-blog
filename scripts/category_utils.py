"""
category_utils.py — canonical HomeOrg category detection.

Maps each article to exactly ONE category from the canonical set:
    Kitchen
    Bathroom and Laundry
    Bedroom and Closets
    Living Room and Entry
    Small Space Guides

Detection uses keyword + title + tags, in that order of specificity.
"""

from __future__ import annotations

from typing import Iterable


CANONICAL_CATEGORIES = (
    "Kitchen",
    "Bathroom and Laundry",
    "Bedroom and Closets",
    "Living Room and Entry",
    "Small Space Guides",
)


# Rules are checked in order; the FIRST match wins.
_RULES = (
    (
        "Kitchen",
        (
            "kitchen", "pantry", "spice", "countertop", "cabinet",
            "cabinets", "fridge", "refrigerator", "galley", "utensil",
            "dish",
        ),
    ),
    (
        "Bathroom and Laundry",
        (
            "bathroom", "bath", "shower", "sink", "toilet", "vanity",
            "powder room", "toiletries", "towel", "tension rod",
            "laundry", "washer", "dryer", "washing machine", "drying rack",
            "hamper", "laundromat",
        ),
    ),
    (
        "Bedroom and Closets",
        (
            "bedroom", "bed", "closet", "wardrobe", "dresser",
            "nightstand", "under bed", "under-bed", "underbed",
            "clothing storage", "hanging clothes",
        ),
    ),
    (
        "Living Room and Entry",
        (
            "living room", "entryway", "entry way", "entry", "foyer",
            "mudroom", "hallway", "console table", "shoe rack", "shoes",
            "coat rack", "keys", "sofa", "couch", "media console",
        ),
    ),
    (
        "Small Space Guides",
        (
            "renter", "rental", "renting", "no drill", "no-drill",
            "drill free", "drill-free", "damage free", "damage-free",
            "removable", "temporary", "declutter", "decluttering",
            "minimalist", "minimalism", "clutter", "purge", "konmari",
            "small space", "small-space", "small apartment", "studio",
            "tiny", "compact", "micro", "5x5", "3ft", "3 ft",
            "home office", "organization", "organizing",
        ),
    ),
)


def detect_category(
    keyword: str = "",
    title: str = "",
    tags: Iterable[str] | None = None,
) -> str:
    """Return exactly ONE canonical category, checking keyword, title, then tags."""
    tags_list = list(tags or [])

    keyword_text = str(keyword or "").lower()
    title_text = str(title or "").lower()
    tags_text = " ".join(str(tag).lower() for tag in tags_list)

    for text in (keyword_text, title_text, tags_text):
        for category, needles in _RULES:
            if any(needle in text for needle in needles):
                return category

    return "Small Space Guides"


def is_canonical(category: str) -> bool:
    """Return whether category exactly matches the canonical category set."""
    return category in CANONICAL_CATEGORIES


# Self-test — run: python scripts/category_utils.py
if __name__ == "__main__":
    cases = [
        ("small bathroom organization ideas", "Small Bathroom Organization Ideas", [], "Bathroom and Laundry"),
        ("small kitchen organization ideas", "Small Kitchen Organization Ideas", [], "Kitchen"),
        ("laundry drying rack", "Laundry Drying Rack", [], "Bathroom and Laundry"),
        ("small bedroom storage ideas", "Small Bedroom Storage Ideas", [], "Bedroom and Closets"),
        ("entryway shoe storage", "Entryway Shoe Storage", [], "Living Room and Entry"),
        ("decluttering a 5x5 home office corner", "Decluttering a 5x5 Home Office Corner", [], "Small Space Guides"),
        ("small space organization", "Small Space Organization", [], "Small Space Guides"),
    ]

    ok = True
    for keyword, title, tags, expected in cases:
        got = detect_category(keyword=keyword, title=title, tags=tags)
        mark = "[OK]" if got == expected else "[FAIL]"
        if got != expected:
            ok = False
        print(f"{mark} {keyword!r}")
        print(f"   expected: {expected}")
        print(f"   got     : {got}")
        print("")

    raise SystemExit(0 if ok else 1)
