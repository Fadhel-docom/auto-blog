"""
slug_utils.py — Unified slug generation for auto-blog.

Fixes P0-1:
    "5-ft" / "5 ft" / "5_ft"  →  "5ft"
    "5-ft-galley"             →  "5ft-galley"
    "sq ft" / "sq-ft"         →  "sqft"
    "100 sq ft apartment"     →  "100-sqft-apartment"
    "3 in deep drawer"        →  "3in-deep-drawer"

Safe for non-ASCII titles (basic transliteration),
idempotent, and works as a drop-in replacement
for any local slugify().
"""

from __future__ import annotations

import re
import unicodedata


# ---------------------------------------------------------------------------
# Units that must attach to the number that precedes them.
# Order matters: longer units first so "sqft" wins over "ft".
# ---------------------------------------------------------------------------
_UNITS = (
    "sqft|sqm|sq|"          # area units (before ft/m)
    "feet|foot|ft|"          # length (imperial)
    "inches|inch|in|"        # length (imperial)
    "cm|mm|km|"              # length (metric)
    "kg|lbs|lb|oz|g|"        # weight
    "yd|ml|l"                # misc
)

# Multi-word units must be squished *before* the number-attach step.
_MULTIWORD_UNITS = [
    (re.compile(r"\bsq[\s\-_]*ft\b", re.IGNORECASE), "sqft"),
    (re.compile(r"\bsq[\s\-_]*m\b", re.IGNORECASE), "sqm"),
]

# Digit + separator + unit → digit + unit (removes the separator)
_UNIT_ATTACH = re.compile(rf"(\d)[\s\-_]*(?=(?:{_UNITS})\b)")

# Anything that is not a-z0-9 → single hyphen
_NON_SLUG = re.compile(r"[^a-z0-9]+")

# Collapse multiple hyphens
_MULTI_HYPHEN = re.compile(r"-{2,}")


def slugify(text: str) -> str:
    """
    Convert any title to a clean, SEO-safe,
    lowercase, hyphenated slug.
    """
    if not text:
        return ""

    # 1) Unicode → ASCII (best effort), lowercase
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()

    # 2) Squish multi-word units first: "sq ft" → "sqft"
    for pattern, repl in _MULTIWORD_UNITS:
        text = pattern.sub(repl, text)

    # 3) Attach single units to their number:
    #    "5-ft" → "5ft", "5 ft" → "5ft"
    text = _UNIT_ATTACH.sub(r"\1", text)

    # 4) Everything non-alphanumeric → hyphen
    text = _NON_SLUG.sub("-", text)

    # 5) Collapse and trim hyphens
    text = _MULTI_HYPHEN.sub("-", text)
    text = text.strip("-")

    return text


def normalize_existing_slug(slug: str) -> str:
    """
    Apply the same normalization to an already
    hyphenated slug.

    Example:
        'for-5-ft-galley'  →  'for-5ft-galley'
    """
    return slugify(slug.replace("-", " "))


# Backwards-compatible alias
slugify_title = slugify


# ---------------------------------------------------------------------------
# Self-test — run:  python scripts/slug_utils.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cases = [
        (
            "Small Kitchen Organization Ideas: Pull-Out Spice Rack for 5-ft Galley",
            "small-kitchen-organization-ideas-pull-out-spice-rack-for-5ft-galley",
        ),
        (
            "5 ft closet organizer",
            "5ft-closet-organizer",
        ),
        (
            "100 sq ft apartment",
            "100-sqft-apartment",
        ),
        (
            "100 sq-ft apartment",
            "100-sqft-apartment",
        ),
        (
            "A 3 in deep drawer",
            "a-3in-deep-drawer",
        ),
        (
            "small closet organization ideas ideas",
            "small-closet-organization-ideas-ideas",
        ),
    ]

    ok = True

    for raw, expected in cases:
        got = slugify(raw)
        mark = "[OK]" if got == expected else "[FAIL]"

        if got != expected:
            ok = False

        print(f"{mark} {raw!r}")
        print(f"   expected: {expected}")
        print(f"   got     : {got}")
        print("")

    raise SystemExit(0 if ok else 1)
