#!/usr/bin/env python3
"""Bulk article quality fixer for Home Organization Ideas.

Deterministic repairs only:
- normalize broken relative image paths
- detect images that belong to a different article and replace them when a
  high-confidence image family for the current article exists
- flag conflicting room-size measurements for review
- keep the existing FAQ/repeated-word cleanup
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "content" / "posts"
IMAGES_DIR = ROOT / "static" / "images"
REPORT_PATH = ROOT / "reports" / "article-fix-report.md"

FAQ_PATTERNS = [
    (re.compile(r"How should I start organizing (.+?) ideas\?", re.I), r"What should I do first when organizing \1?"),
    (re.compile(r"What are the best ways to organize (.+?) ideas\?", re.I), r"How do I organize \1?"),
    (re.compile(r"What is the best way to organize (.+?) ideas\?", re.I), r"How do I organize \1?"),
    (re.compile(r"What are some organizing (.+?) ideas\?", re.I), r"What are some practical ways to organize \1?"),
    (re.compile(r"How can I organize (.+?) ideas\?", re.I), r"How can I organize \1?"),
]
REPEATED_WORD = re.compile(r"\b([A-Za-z][A-Za-z\'-]*)\s+\1\b", re.I)
MEASUREMENT = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:×|x|X|by)\s*\d+(?:\.\d+)?\s*(?:ft|feet|foot|sq\s*ft|square feet)?\b",
    re.I,
)
H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
IMAGE_PATH = re.compile(r"(?P<prefix>\]\()(?P<path>(?:\.\./)+images/|/images/)(?P<name>[^)\s]+)(?P<suffix>\))")
STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "with",
    "your", "you", "is", "are", "how", "what", "can", "do", "ideas", "best",
    "ways", "way", "organize", "organization", "organizing", "small", "practical",
    "space", "home", "without", "adding", "more", "make", "use", "using",
}

def tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower())
        if w not in STOPWORDS and len(w) > 2
    }

def h2_similarity(a: str, b: str) -> float:
    aa, bb = tokens(a), tokens(b)
    return len(aa & bb) / len(aa | bb) if aa and bb else 0.0

def image_family(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"-(?:\d+)$", "", stem)

def image_score(article_stem: str, image_name: str) -> float:
    a, b = tokens(article_stem), tokens(image_family(image_name))
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    # Require at least two meaningful shared terms for ownership.
    if overlap < 2:
        return 0.0
    return overlap / len(a | b)

def available_image_families() -> dict[str, list[str]]:
    families: dict[str, list[str]] = {}
    if not IMAGES_DIR.exists():
        return families
    for path in sorted(IMAGES_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            families.setdefault(image_family(path.name), []).append(path.name)
    return families

def best_image_family(article_stem: str, families: dict[str, list[str]]) -> tuple[str | None, float]:
    ranked = sorted(
        ((family, image_score(article_stem, family)) for family in families),
        key=lambda item: (-item[1], item[0]),
    )
    if not ranked:
        return None, 0.0
    return ranked[0] if ranked[0][1] >= 0.45 else (None, ranked[0][1])

def fix_deterministic(text: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    for pattern, replacement in FAQ_PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            changes.append(f"FAQ wording: {n}")
    text, n = REPEATED_WORD.subn(lambda m: m.group(1), text)
    if n:
        changes.append(f"repeated words: {n}")
    return text, changes

def normalize_image_paths(text: str) -> tuple[str, int]:
    def repl(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}/auto-blog/images/{match.group('name')}{match.group('suffix')}"
    return IMAGE_PATH.subn(repl, text)

def replace_wrong_images(
    text: str,
    article_stem: str,
    families: dict[str, list[str]],
) -> tuple[str, list[str], list[str]]:
    family, score = best_image_family(article_stem, families)
    changes: list[str] = []
    review: list[str] = []

    def repl(match: re.Match[str]) -> str:
        src = match.group("name")
        if src.startswith("http://") or src.startswith("https://"):
            return match.group(0)

        current_family = image_family(src)
        current_score = image_score(article_stem, src)

        # A clearly owned image needs no action.
        if current_score >= 0.45:
            return match.group(0)

        if family and score >= 0.55:
            replacement = families[family][0]
            if replacement != src:
                changes.append(f"image ownership: {src} -> {replacement}")
                return f"{match.group('prefix')}/auto-blog/images/{replacement}{match.group('suffix')}"
            return match.group(0)

        review.append(f"image ownership review: {src} (article={article_stem}, best_score={score:.2f})")
        return match.group(0)

    fixed = IMAGE_PATH.sub(repl, text)
    # Also inspect already-normalized /auto-blog/images/ paths.
    normalized_image = re.compile(r"(?P<prefix>!\[[^\]]*\]\(/auto-blog/images/)(?P<name>[^)\s]+)(?P<suffix>\))")

    def inspect_normalized(match: re.Match[str]) -> str:
        src = match.group("name")
        current_score = image_score(article_stem, src)
        if current_score >= 0.45:
            return match.group(0)
        if family and score >= 0.55:
            replacement = families[family][0]
            if replacement != src:
                changes.append(f"image ownership: {src} -> {replacement}")
                return f"{match.group('prefix')}{replacement}{match.group('suffix')}"
        review.append(f"image ownership review: {src} (article={article_stem}, best_score={score:.2f})")
        return match.group(0)

    fixed = normalized_image.sub(inspect_normalized, fixed)
    return fixed, changes, review

def inspect_article(
    path: Path,
    apply: bool,
    families: dict[str, list[str]],
) -> dict:
    original = path.read_text(encoding="utf-8")
    fixed, changes = fix_deterministic(original)

    fixed, path_count = normalize_image_paths(fixed)
    if path_count:
        changes.append(f"image paths normalized: {path_count}")

    fixed, image_changes, image_review = replace_wrong_images(
        fixed, path.stem, families
    )
    changes.extend(image_changes)

    h2s = H2.findall(fixed)
    duplicate_h2s = []
    for i, left in enumerate(h2s):
        for right in h2s[i + 1:]:
            score = h2_similarity(left, right)
            if score >= 0.65:
                duplicate_h2s.append((left, right, score))

    measurements = sorted(set(MEASUREMENT.findall(fixed)))
    measurement_flag = len(measurements) >= 2

    if apply and fixed != original:
        path.write_text(fixed, encoding="utf-8")

    return {
        "file": path.name,
        "fixed": changes,
        "h2": duplicate_h2s,
        "measurements": measurements,
        "measurement_flag": measurement_flag,
        "image_review": image_review,
    }

def build_report(rows: list[dict]) -> str:
    lines = [
        "# Bulk Article Fix Report",
        "",
        f"- Articles scanned: **{len(rows)}**",
        f"- Articles changed automatically: **{sum(bool(r['fixed']) for r in rows)}**",
        f"- Image paths normalized: **{sum(sum(1 for x in r['fixed'] if x.startswith('image paths normalized:')) for r in rows)} articles**",
        f"- Wrong-image replacements: **{sum(sum(1 for x in r['fixed'] if x.startswith('image ownership:')) for r in rows)}**",
        f"- Image ownership unresolved: **{sum(len(r['image_review']) for r in rows)}**",
        f"- Conflicting measurements: **{sum(bool(r['measurement_flag']) for r in rows)} articles**",
        "",
        "| # | Article | Issues | Fixed | Needs Review |",
        "|---:|---|---|---|---|",
    ]

    for i, r in enumerate(rows, 1):
        issues: list[str] = []
        review: list[str] = []
        if r["h2"]:
            issues.append(f"H2 similarity x{len(r['h2'])}")
            review.append("H2")
        if r["measurement_flag"]:
            issues.append(f"measurements x{len(r['measurements'])}")
            review.append("measurements")
        if r["image_review"]:
            issues.append(f"image ownership x{len(r['image_review'])}")
            review.append("image ownership")
        if r["fixed"]:
            issues.extend(r["fixed"])
        lines.append(
            f"| {i} | {r['file']} | {'; '.join(issues) or '-'} | "
            f"{'Yes' if r['fixed'] else 'No'} | {'; '.join(review) or 'No'} |"
        )

    lines += ["", "## Human-review details", ""]
    for r in rows:
        if not (r["h2"] or r["measurement_flag"] or r["image_review"]):
            continue
        lines.append(f"### {r['file']}")
        for a, b, score in r["h2"]:
            lines.append(f"- H2 similarity {score:.2f}: {a} <-> {b}")
        if r["measurement_flag"]:
            lines.append("- Measurements: " + ", ".join(r["measurements"]))
        for item in r["image_review"]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines) + "\n"

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report only; do not modify posts")
    args = parser.parse_args()

    paths = sorted(p for p in POSTS_DIR.glob("*.md") if p.is_file())
    families = available_image_families()
    rows = [inspect_article(p, apply=not args.check, families=families) for p in paths]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build_report(rows), encoding="utf-8")

    print(f"Scanned {len(rows)} articles")
    print(f"Automatic fixes: {sum(len(r['fixed']) for r in rows)}")
    print(f"Image ownership reviews: {sum(len(r['image_review']) for r in rows)}")
    print(f"Articles with conflicting measurements: {sum(bool(r['measurement_flag']) for r in rows)}")
    print(f"Report: {REPORT_PATH}")

if __name__ == "__main__":
    raise SystemExit(main())
