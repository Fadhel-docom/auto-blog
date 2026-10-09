#!/usr/bin/env python3
"""Hard safety gate for automated article publishing.

This gate is intentionally conservative: it blocks obviously incomplete,
thin, duplicated, or legacy low-quality output before the workflow commits.
It does not rewrite content and never sends traffic.
"""
from pathlib import Path
import hashlib
import re
import sys
from datetime import datetime

POSTS = Path("content/posts")
MIN_WORDS = 1500
MIN_IMAGES = 5
MIN_H2 = 8
MIN_FAQ = 4

STOP = {
    "a","an","and","are","as","at","be","by","for","from","how","in","into",
    "is","it","of","on","or","that","the","this","to","with","your","you",
    "home","ideas","organization","organizing","organize","small","space",
    "spaces","tips","guide","simple","practical","ways"
}

def frontmatter(text):
    if not text.startswith("+++"):
        return "", text
    end = text.find("\n+++\n", 3)
    if end == -1:
        return "", text
    return text[3:end], text[end + 5:]

def field(fm, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*(.+)$", fm, re.M)
    return m.group(1).strip() if m else ""

def post_date(text):
    fm, _ = frontmatter(text)
    raw = quoted_value(field(fm, "date"))
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0

def normalize_image_ref(value):
    value = str(value or "").strip()
    value = value.split("?", 1)[0].split("#", 1)[0]
    value = value.replace("\\", "/")
    if value.startswith("/images/"):
        return value
    if "/images/" in value:
        return "/images/" + value.rsplit("/images/", 1)[1]
    if value.startswith("images/"):
        return "/" + value
    return value

def local_image_hashes(post):
    hashes = {}
    for raw in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", post):
        value = normalize_image_ref(raw)
        if not value.startswith("/images/"):
            continue
        path = Path("static") / value.lstrip("/")
        if not path.exists() or not path.is_file():
            continue
        try:
            hashes[value] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    return hashes

def quoted_value(v):
    m = re.match(r'^[\"\'](.*)[\"\']$', v)
    return m.group(1) if m else v

def word_count(body):
    return len(re.findall(r"\b[\w’'-]+\b", body))

def tokens(text):
    return [w.lower() for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) > 2 and w.lower() not in STOP]

def shingles(text, size=4):
    t = tokens(text)
    return {" ".join(t[i:i+size]) for i in range(max(0, len(t)-size+1))}

def main(target_post=None):
    posts = [p for p in POSTS.glob("*.md") if p.name != ".gitkeep"]
    if not posts:
        print("CONTENT GATE: no posts found")
        return 0

    if target_post:
        post = Path(target_post)
        if not post.is_file() or post.suffix.lower() != ".md":
            print(f"CONTENT GATE: target post not found: {post}")
            return 1
    else:
        # GitHub Actions checkout mtimes are not editorial dates.
        post = max(posts, key=lambda p: post_date(p.read_text(encoding="utf-8")))
    text = post.read_text(encoding="utf-8")
    fm, body = frontmatter(text)

    errors = []
    title = quoted_value(field(fm, "title"))
    description = quoted_value(field(fm, "description"))

    if not title:
        errors.append("missing title")
    elif not 35 <= len(title) <= 100:
        errors.append(f"title length {len(title)} outside 35-100")

    if not description:
        errors.append("missing description")
    elif not 80 <= len(description) <= 220:
        errors.append(f"description length {len(description)} outside 80-220")

    # Hand-built guides with original diagrams (original_graphics = true) carry part of the
    # explanation in their diagrams, so their text/image floors are lower. Counts are floors,
    # not goals: the checks below on sources, alt text and unique images still apply to all posts.
    original_graphics = bool(re.search(r"^original_graphics\s*=\s*true", fm, re.M))
    min_words = 1200 if original_graphics else MIN_WORDS
    min_images = 3 if original_graphics else MIN_IMAGES
    words = word_count(body)
    if words < min_words:
        errors.append(f"only {words} body words; minimum is {min_words}")

    image_urls = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body)
    images = len(image_urls)
    if images < min_images:
        errors.append(f"only {images} inline images; minimum is {min_images}")

    for alt_text in re.findall(r"!\[([^\]]*)\]\(", body):
        if len(alt_text.strip()) < 15 or re.search(r"\.(jpe?g|png|svg|webp)$", alt_text.strip(), re.I):
            errors.append(f"image alt text too short or filename-like: {alt_text[:40]!r}")
            break

    sources_match = re.search(r"^##+\s+(Sources|References)\b.*?$(.*?)(?=^##\s|\Z)", body, re.M | re.S | re.I)
    if not sources_match or not re.search(r"\]\(https?://[^)\s]+\)", sources_match.group(2)):
        errors.append("missing Sources section with at least one external https link")

    normalized_urls = [normalize_image_ref(x) for x in image_urls]
    if len(set(normalized_urls)) != len(normalized_urls):
        errors.append("duplicate inline image URL detected")

    for image_url in normalized_urls:
        if image_url.startswith("/images/"):
            image_path = Path("static") / image_url.lstrip("/")
            if not image_path.exists() or not image_path.is_file() or image_path.stat().st_size <= 0:
                errors.append(f"missing or empty local image: {image_url}")

    hero = normalize_image_ref(quoted_value(field(fm, "image")))
    original_graphics = field(fm, "original_graphics").strip().lower() == "true"
    # Posts with a purpose-built cover (original_graphics = true) may use a cover
    # that is not repeated inline; every other post keeps the strict rule.
    if hero and not original_graphics and hero not in normalized_urls:
        errors.append(f"featured image is not one of this article's inline images: {hero}")

    used_by_other = {}
    for other in posts:
        if other == post:
            continue
        other_text = other.read_text(encoding="utf-8")
        other_fm, other_body = frontmatter(other_text)
        refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", other_body)
        refs.append(field(other_fm, "image"))
        for other_url in refs:
            canonical = normalize_image_ref(other_url)
            if canonical:
                used_by_other.setdefault(canonical, other.name)
    for image_url in normalized_urls:
        prior = used_by_other.get(image_url)
        if prior:
            errors.append(f"image reference already used by {prior}: {image_url}")
            break

    current_hashes = local_image_hashes(body)
    all_hashes = {}
    for other in posts:
        if other == post:
            continue
        other_text = other.read_text(encoding="utf-8")
        for image_url, digest in local_image_hashes(other_text).items():
            all_hashes.setdefault(digest, other.name)
    for image_url, digest in current_hashes.items():
        if digest in all_hashes:
            errors.append(f"image file is byte-identical to {all_hashes[digest]}: {image_url}")
            break

    if images > 0 and image_urls:
        for image_url in image_urls:
            if not image_url.strip():
                errors.append("empty inline image URL")
                break

    h2 = len(re.findall(r"^##\s+\S", body, re.M))
    if h2 < MIN_H2:
        errors.append(f"only {h2} H2 sections; minimum is {MIN_H2}")

    faq_count = len(re.findall(r"question\s*=", fm, re.I))
    if faq_count < MIN_FAQ:
        errors.append(f"only {faq_count} FAQ questions; minimum is {MIN_FAQ}")

    forbidden_markers = [
        "generated by groq",
        "groq api",
        "lorem ipsum",
        "as an ai language model",
    ]
    lower = text.lower()
    for marker in forbidden_markers:
        if marker in lower:
            errors.append(f"forbidden legacy marker: {marker}")

    # Duplicate protection is deliberately broader than exact-title matching.
    # It catches closely reworded titles and articles sharing substantial
    # four-word sequences, while ignoring generic home-organization vocabulary.
    current_title_tokens = set(tokens(title))
    current_shingles = shingles(body)
    for other in posts:
        if other == post:
            continue
        other_text = other.read_text(encoding="utf-8")
        ofm, obody = frontmatter(other_text)
        other_title = quoted_value(field(ofm, "title"))
        other_title_tokens = set(tokens(other_title))

        if title and other_title and title.casefold() == other_title.casefold():
            errors.append(f"duplicate title with {other.name}")
            break

        title_overlap = len(current_title_tokens & other_title_tokens)
        smaller_title = min(len(current_title_tokens), len(other_title_tokens))
        if smaller_title >= 2 and title_overlap >= 2 and title_overlap / smaller_title >= 0.66:
            errors.append(f"near-duplicate title/topic with {other.name}")
            break

        if len(current_shingles) >= 20:
            other_shingles = shingles(obody)
            union = current_shingles | other_shingles
            overlap = len(current_shingles & other_shingles) / max(1, len(union))
            if overlap >= 0.025:
                errors.append(f"high content overlap with {other.name} ({overlap:.1%} four-word shingles)")
                break

    if errors:
        print(f"CONTENT GATE: BLOCKED {post}")
        for error in errors:
            print(f" - {error}")
        return 1

    print(
        f"CONTENT GATE: PASS {post.name} | words={words} "
        f"images={images} h2={h2} faq={faq_count}"
    )
    return 0

if __name__ == "__main__":
    target = None
    if len(sys.argv) > 1:
        target = sys.argv[1]
    sys.exit(main(target))
