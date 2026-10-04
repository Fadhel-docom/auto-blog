from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSTS_DIR = ROOT / "content" / "posts"
IMAGES_DIR = ROOT / "static" / "images"
REPORT_PATH = ROOT / "reports" / "image_paths_report.md"

SITE_HOST_RE = r"https://fadhel-docom\.github\.io"
SITE_ORIGIN = "https://fadhel-docom.github.io"


LOCAL_IMAGE_RE = re.compile(
    rf"""(?<![A-Za-z0-9._%+@/-])(?P<token>
        (?:
            \${SITE_HOST_RE}/(?:auto-blog/)?images/[A-Za-z0-9._%+@-]+(?:/[A-Za-z0-9._%+@-]+)*
            |
            /auto-blog/images/[A-Za-z0-9._%+@-]+(?:/[A-Za-z0-9._%+@-]+)*
            |
            /images/[A-Za-z0-9._%+@-]+(?:/[A-Za-z0-9._%+@-]+)*
            |
            (?:\.\./)+images/[A-Za-z0-9._%+@-]+(?:/[A-Za-z0-9._%+@-]+)*
            |
            images/[A-Za-z0-9._%+@-]+(?:/[A-Za-z0-9._%+@-]+)*
        )
    )""",
    re.VERBOSE,
)


def filename_from_token(token: str) -> str:
    path = token

    if path.startswith(SITE_ORIGIN):
        path = re.sub(r"^https://fadhel-docom\.github\.io", "", path)

    path = re.sub(r"^/auto-blog/", "/", path)
    path = re.sub(r"^(?:\.\./)+", "", path)
    path = path.lstrip("/")

    if not path.startswith("images/"):
        return ""

    return path[len("images/"):]


def process_post(path, apply, unresolved):
    original = path.read_text(encoding="utf-8")

    replacements = 0
    seen_unresolved = set()

    def replace_reference(match):
        nonlocal replacements

        token = match.group("token")
        filename = filename_from_token(token)

        if not filename:
            return token

        target = IMAGES_DIR / filename

        if not target.is_file():
            item = (str(path.relative_to(POSTS_DIR)), token)
            if item not in seen_unresolved:
                unresolved.append(item)
                seen_unresolved.add(item)
            return token

        replacement = f"images/{filename}"

        if replacement != token:
            replacements += 1

        return replacement

    updated = LOCAL_IMAGE_RE.sub(replace_reference, original)
    changed = updated != original

    if changed and apply:
        path.write_text(updated, encoding="utf-8")

    return changed, replacements


def write_report(scanned, changed_posts, replacements, unresolved, apply):
    lines = [
        "# Image Paths Report",
        "",
        f"- Mode: **{'apply' if apply else 'dry-run'}**",
        f"- Posts scanned: **{scanned}**",
        f"- Posts changed: **{changed_posts}**",
        f"- Image paths normalized: **{replacements}**",
        "",
        "## Unresolved references",
        "",
    ]

    if unresolved:
        for post_name, token in unresolved:
            lines.append(f"- `{post_name}` → `{token}`")
    else:
        lines.append("None.")

    lines.extend(["", f"Unresolved references: **{len(unresolved)}**", ""])

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize local article image paths."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write normalized paths to article files.",
    )
    args = parser.parse_args()

    posts = sorted(POSTS_DIR.rglob("*.md")) if POSTS_DIR.exists() else []

    unresolved = []
    changed_posts = 0
    replacements = 0

    for post in posts:
        changed, count = process_post(post, args.apply, unresolved)
        if changed:
            changed_posts += 1
        replacements += count

    write_report(
        scanned=len(posts),
        changed_posts=changed_posts,
        replacements=replacements,
        unresolved=unresolved,
        apply=args.apply,
    )

    print(f"Posts scanned: {len(posts)}")
    print(f"Posts changed: {changed_posts}")
    print(f"Image paths normalized: {replacements}")
    print(f"Unresolved references: {len(unresolved)}")
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
