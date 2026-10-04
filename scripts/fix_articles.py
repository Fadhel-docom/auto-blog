#!/usr/bin/env python3
"""Bulk article quality fixer for Home Organization Ideas.

Deterministic repairs:
- normalize broken relative image paths
- preserve image content while giving cross-article images article-local aliases
- report genuinely different measurements without changing them
- keep existing FAQ/repeated-word cleanup
"""

from __future__ import annotations

import argparse
import re
import shutil
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
    r"\b(\d+(?:\.\d+)?)\s*(?:×|x|X|by)\s*(\d+(?:\.\d+)?)\s*(?:ft|feet|foot|sq\s*ft|square feet)?\b",
    re.I,
)
H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
IMAGE_PATH = re.compile(
    r"(?P<prefix>\]\()(?P<path>(?:\.\./)+images/|/images/|/auto-blog/images/)(?P<name>[^)\s]+)(?P<suffix>\))"
)
STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "with",
    "your", "you", "is", "are", "how", "what", "can", "do", "ideas", "best",
    "ways", "way", "organize", "organization", "organizing", "small", "practical",
    "space", "home", "without", "adding", "more", "make", "use", "using",
}

def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if w not in STOPWORDS and len(w) > 2}

def h2_similarity(a: str, b: str) -> float:
    aa, bb = tokens(a), tokens(b)
    return len(aa & bb) / len(aa | bb) if aa and bb else 0.0

def image_family(name: str) -> str:
    return re.sub(r"-(?:\d+)$", "", Path(name).stem.lower())

def image_score(article_stem: str, image_name: str) -> float:
    a, b = tokens(article_stem), tokens(image_family(image_name))
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    return overlap / len(a | b) if overlap >= 2 else 0.0

def available_image_families() -> dict[str, list[str]]:
    families: dict[str, list[str]] = {}
    if IMAGES_DIR.exists():
        for path in sorted(IMAGES_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                families.setdefault(image_family(path.name), []).append(path.name)
    return families

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

def alias_name(article_stem: str, source_name: str) -> str:
    safe = re.sub(r"[^a-z0-9-]+", "-", article_stem.lower()).strip("-")
    return f"{safe}--alias--{Path(source_name).name}"

def alias_image(article_stem: str, source_name: str, apply: bool) -> str | None:
    source = IMAGES_DIR / Path(source_name).name
    if not source.is_file():
        return None
    target_name = alias_name(article_stem, source.name)
    target = IMAGES_DIR / target_name
    if apply and not target.exists():
        shutil.copy2(source, target)
    return target_name

def replace_wrong_images(text: str, article_stem: str, families: dict[str, list[str]], apply: bool):
    changes: list[str] = []
    review: list[str] = []

    def repl(match: re.Match[str]) -> str:
        src = match.group("name")
        if src.startswith(("http://", "https://")):
            return match.group(0)

        current_score = image_score(article_stem, src)
        if current_score >= 0.45:
            return match.group(0)

        # Score 0.00: preserve exact image bytes by creating an article-local alias.
        if current_score == 0.0:
            target = alias_image(article_stem, src, apply)
            if target:
                changes.append(f"image alias: {src} -> {target}")
                return f"{match.group('prefix')}/auto-blog/images/{target}{match.group('suffix')}"
            review.append(f"image alias unavailable: {src} (source not found)")
            return match.group(0)

        review.append(f"image ownership review: {src} (article={article_stem}, score={current_score:.2f})")
        return match.group(0)

    return IMAGE_PATH.sub(repl, text), changes, review

def measurement_key(pair: tuple[str, str]) -> tuple[float, float]:
    return float(pair[0]), float(pair[1])

def inspect_article(path: Path, apply: bool, families: dict[str, list[str]]) -> dict:
    original = path.read_text(encoding="utf-8")
    fixed, changes = fix_deterministic(original)

    fixed, path_count = normalize_image_paths(fixed)
    if path_count:
        changes.append(f"image paths normalized: {path_count}")

    fixed, image_changes, image_review = replace_wrong_images(fixed, path.stem, families, apply)
    changes.extend(image_changes)

    h2s = H2.findall(fixed)
    duplicate_h2s = []
    for i, left in enumerate(h2s):
        for right in h2s[i + 1:]:
            score = h2_similarity(left, right)
            if score >= 0.65:
                duplicate_h2s.append((left, right, score))

    raw_measurements = MEASUREMENT.findall(fixed)
    distinct_measurements = sorted({measurement_key(v) for v in raw_measurements})
    measurements = [f"{a:g} × {b:g}" for a, b in distinct_measurements]
    # 5x5 and 5×5 collapse to one value; only genuinely different dimensions are flagged.
    measurement_flag = len(distinct_measurements) > 1

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
    alias_count = sum(sum(1 for x in r["fixed"] if x.startswith("image alias:")) for r in rows)
    normalized_count = sum(
        int(x.split(": ", 1)[1]) for r in rows for x in r["fixed"]
        if x.startswith("image paths normalized:")
    )
    unresolved = sum(len(r["image_review"]) for r in rows)
    measurement_conflicts = sum(bool(r["measurement_flag"]) for r in rows)

    lines = [
        "# Bulk Article Fix Report", "",
        f"- Articles scanned: **{len(rows)}**",
        f"- Articles changed automatically: **{sum(bool(r['fixed']) for r in rows)}**",
        f"- Image paths normalized: **{normalized_count}**",
        f"- Image ownership aliases created: **{alias_count}**",
        f"- Image ownership unresolved: **{unresolved}**",
        f"- Genuine measurement conflicts: **{measurement_conflicts} articles**",
        "", "## Measurement conflicts — user review only", "",
    ]

    conflicts = [r for r in rows if r["measurement_flag"]]
    if conflicts:
        for r in conflicts:
            lines.append(f"- **{r['file']}**: " + " + ".join(r["measurements"]))
    else:
        lines.append("- None")

    lines += ["", "## Article details", "",
              "| # | Article | Issues | Fixed | Needs Review |",
              "|---:|---|---|---|---|"]

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
        lines.append(f"| {i} | {r['file']} | {'; '.join(issues) or '-'} | "
                     f"{'Yes' if r['fixed'] else 'No'} | {'; '.join(review) or 'No'} |")

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
    parser.add_argument("--check", action="store_true", help="report only; do not modify posts or create aliases")
    args = parser.parse_args()

    paths = sorted(p for p in POSTS_DIR.glob("*.md") if p.is_file())
    families = available_image_families()
    rows = [inspect_article(p, apply=not args.check, families=families) for p in paths]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(build_report(rows), encoding="utf-8")

    print(f"Scanned {len(rows)} articles")
    print(f"Automatic fixes: {sum(len(r['fixed']) for r in rows)}")
    print(f"Image aliases created: {sum(sum(1 for x in r['fixed'] if x.startswith('image alias:')) for r in rows)}")
    print(f"Image ownership unresolved: {sum(len(r['image_review']) for r in rows)}")
    print(f"Genuine measurement conflicts: {sum(bool(r['measurement_flag']) for r in rows)}")
    print(f"Report: {REPORT_PATH}")

if __name__ == "__main__":
    raise SystemExit(main())
