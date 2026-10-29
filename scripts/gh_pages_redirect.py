#!/usr/bin/env python3
"""Turn the GitHub Pages build into a redirect copy of the canonical site.

The canonical site is https://home-organization-ideas.pages.dev/ (Cloudflare Pages).
The GitHub Pages copy stays online so old links keep working, but every page
points to the canonical URL (canonical tag, Open Graph, JSON-LD, sitemap,
robots.txt) and redirects visitors to the same page on the canonical site.

Usage: python scripts/gh_pages_redirect.py [public_dir]
"""
import re
import sys
from pathlib import Path

OLD = "https://fadhel-docom.github.io/auto-blog/"
NEW = "https://home-organization-ideas.pages.dev/"
TEXT_SUFFIXES = {".html", ".xml", ".txt", ".json"}
HEAD_RE = re.compile(r"<head[^>]*>", re.IGNORECASE)


def target_for(public: Path, page: Path) -> str:
    if page.name == "404.html" and page.parent == public:
        return NEW
    rel = page.parent.relative_to(public).as_posix()
    return NEW if rel == "." else NEW + rel + "/"


def main() -> int:
    public = Path(sys.argv[1] if len(sys.argv) > 1 else "public")
    if not public.is_dir():
        print(f"ERROR: {public} is not a directory")
        return 1
    rewritten = redirected = 0
    for path in sorted(public.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        new = text.replace(OLD, NEW).replace(OLD.rstrip("/"), NEW.rstrip("/"))
        if path.suffix.lower() == ".html" and path.name in {"index.html", "404.html"}:
            if "http-equiv=\"refresh\"" not in new:
                tag = f'<meta http-equiv="refresh" content="0;url={target_for(public, path)}">'
                new, count = HEAD_RE.subn(lambda m: m.group(0) + tag, new, count=1)
                redirected += count
        if new != text:
            path.write_text(new, encoding="utf-8")
            rewritten += 1
    print(f"gh_pages_redirect: {rewritten} files rewritten, {redirected} pages redirect to {NEW}")
    return 0 if redirected else 1


if __name__ == "__main__":
    sys.exit(main())
