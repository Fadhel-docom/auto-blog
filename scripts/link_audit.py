#!/usr/bin/env python3
"""Verify internal links and assets in the built site."""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

PUBLIC_DIR = Path("public")
SITE_PREFIX = "/auto-blog"
SKIP_SCHEMES = (
    "http://", "https://", "mailto:", "tel:",
    "javascript:", "data:"
)


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        for name, value in attrs:
            if name.lower() in ("href", "src") and value:
                self.links.append(value)


def normalize_target(link: str, current_file: Path) -> Path | None:
    link = link.split("#", 1)[0].split("?", 1)[0].strip()
    if not link or link.startswith(SKIP_SCHEMES):
        return None

    path = unquote(urlparse(link).path)

    if path.startswith(SITE_PREFIX):
        path = path[len(SITE_PREFIX):]
    elif not path.startswith("/"):
        rel_dir = current_file.parent.relative_to(PUBLIC_DIR)
        path = "/" + str((rel_dir / path).as_posix())

    path = path.lstrip("/") or "index.html"
    candidate = PUBLIC_DIR / path

    if candidate.is_dir():
        return candidate / "index.html"
    if candidate.exists():
        return candidate

    if not candidate.suffix:
        alt = candidate / "index.html"
        if alt.exists():
            return alt
        alt = candidate.with_suffix(".html")
        if alt.exists():
            return alt

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
        text = page.read_text(encoding="utf-8", errors="ignore")
        parser = LinkExtractor()
        parser.feed(text)

        for link in parser.links:
            total_links += 1
            target = normalize_target(link, page)
            if target is None:
                continue
            checked += 1
            if not target.exists():
                broken.append((page, link))

    print(
        f"[AUDIT] pages={len(html_files)} "
        f"links={total_links} checked={checked} broken={len(broken)}"
    )

    for page, link in broken[:50]:
        print(f"  ✗ {page.relative_to(PUBLIC_DIR)} -> {link}")

    if len(broken) > 50:
        print(f"  ... and {len(broken) - 50} more")

    if broken:
        return 1

    print("[OK] no broken internal links found.")
    return 0


if __name__ == "__main__":
    sys.exit(audit())
