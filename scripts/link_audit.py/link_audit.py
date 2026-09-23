#!/usr/bin/env python3
"""
link_audit.py — verify internal links and assets in the built site (public/).

Scans every HTML file under public/ and checks that every internal href/src
resolves to an actual file. Reports broken links and exits non-zero on failure.
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, unquote

PUBLIC_DIR = Path("public")
SITE_PREFIX = "/auto-blog"
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "javascript:", "data:")


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() in ("href", "src") and value:
                self.links.append(value)


def normalize_target(link: str, current_file: Path) -> Path | None:
    link = link.split("#", 1)[0].split("?", 1)[0].strip()
    if not link or link.startswith(SKIP_SCHEMES):
        return None

    parsed = urlparse(link)
    path = unquote(parsed.path)

    if path.startswith(SITE_PREFIX):
        path = path[len(SITE_PREFIX):]
    elif path.startswith("/"):
        pass
    else:
        rel_dir = current_file.parent.relative_to(PUBLIC_DIR)
        path = "/" + str((rel_dir / path).as_posix())

    path = path.lstrip("/")
    if not path:
        path = "index.html"

    candidate = PUBLIC_DIR / path

    if candidate.is_dir():
        return candidate / "index.html"

    if candidate.exists():
        return candidate

    if not candidate.suffix:
        alt = PUBLIC_DIR / path / "index.html"
        if alt.exists():
            return alt
        alt2 = candidate.with_suffix(".html")
        if alt2.exists():
            return alt2

    return candidate


def audit() -> int:
    if not PUBLIC_DIR.exists():
        print(f"[ERROR] {PUBLIC_DIR} not found. Run Hugo build first.")
        return 2

    html_files = list(PUBLIC_DIR.rglob("*.html"))
    if not html_files:
        print("[ERROR] no HTML files in public/")
        return 2

    broken: list[tuple[Path, str]] = []
    total_links = 0
    checked = 0

    for page in html_files:
        try:
            text = page.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        parser = LinkExtractor()
        try:
            parser.feed(text)
        except Exception:
            continue

        for link in parser.links:
            total_links += 1
            target = normalize_target(link, page)
            if target is None:
                continue
            checked += 1
            if not target.exists():
                broken.append((page, link))

    print(f"[AUDIT] pages={len(html_files)} links={total_links} checked={checked} broken={len(broken)}")

    if broken:
        for page, link in broken[:50]:
            rel = page.relative_to(PUBLIC_DIR)
            print(f"  ✗ {rel}  ->  {link}")
        if len(broken) > 50:
            print(f"  ... and {len(broken) - 50} more")
        return 1

    print("[OK] no broken internal links found.")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
