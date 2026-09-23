#!/usr/bin/env python3

import json
import os
import re

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from bs4 import BeautifulSoup


ROOT_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT_DIR / "logs"

SITE_URL = os.getenv(
    "SITE_URL",
    "https://fadhel-docom.github.io/auto-blog/",
).rstrip("/") + "/"

REPORT_PATH = LOG_DIR / "ui_report.json"
SUGGESTIONS_PATH = LOG_DIR / "ui_suggestions.json"

TIMEOUT = 20

GOLDEN = {
    "home": {
        "required_text": [
            "Home Organization Ideas",
            "Explore by room",
            "Featured organization guides",
            "Latest organization guides",
        ],
        "required_controls": ["search"],
        "minimum_article_cards": 6,
    },
    "article": {
        "required": [
            "title",
            "description",
            "image",
            "tags",
            "schema",
            "image credits",
            "related",
        ],
        "minimum_h2": 3,
    },
}


def now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )


def ensure_logs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def fetch(url: str) -> requests.Response:
    return requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent": "auto-blog-ui-checker",
        },
    )


def soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def check_home() -> dict[str, Any]:
    response = fetch(SITE_URL)
    html = response.text
    page = soup(html)

    text = page.get_text(" ", strip=True)

    missing_text = [
        item for item in GOLDEN["home"]["required_text"]
        if item.lower() not in text.lower()
    ]

    nav_links = [
        anchor.get("href")
        for anchor in page.select("nav a, header a")
        if anchor.get("href")
    ]

    search_controls = page.select(
        'input[type="search"], '
        'input[name*="search" i], '
        '[data-search], '
        'form[action*="search" i]'
    )

    cards = page.select(
        "article, .post-card, .card, .article-card"
    )

    hero = (
        page.select_one(
            ".hero, [class*='hero' i], header"
        )
        is not None
    )

    featured = "featured" in text.lower()

    return {
        "url": SITE_URL,
        "status": response.status_code,
        "hero": hero,
        "search": bool(search_controls),
        "grid": len(cards) >= 1,
        "featured": featured,
        "nav_links": len(nav_links),
        "article_cards": len(cards),
        "missing_text": missing_text,
        "title": (
            page.title.get_text(strip=True)
            if page.title else None
        ),
        "viewport": bool(
            page.select_one('meta[name="viewport"]')
        ),
        "html_length": len(html),
    }


def extract_article_urls(
    home_html: str,
) -> list[str]:
    page = soup(home_html)
    urls = []

    for anchor in page.select("a[href]"):
        href = anchor.get("href", "")
        absolute = urljoin(SITE_URL, href)

        if "/posts/" not in absolute:
            continue

        if absolute not in urls:
            urls.append(absolute)

    return urls[:5]


def check_json_ld(
    page: BeautifulSoup,
) -> dict[str, Any]:
    scripts = page.select(
        'script[type="application/ld+json"]'
    )

    parsed = []

    for script in scripts:
        raw = script.string or script.get_text()

        try:
            data = json.loads(raw)

            if isinstance(data, list):
                parsed.extend(data)
            else:
                parsed.append(data)

        except Exception:
            parsed.append({"_invalid_json": True})

    types = []

    for item in parsed:
        if isinstance(item, dict):
            value = item.get("@type")

            if isinstance(value, list):
                types.extend(value)
            elif value:
                types.append(str(value))

    return {
        "present": bool(scripts),
        "valid_blocks": sum(
            1 for item in parsed
            if not item.get("_invalid_json")
            if isinstance(item, dict)
        ),
        "types": sorted(set(types)),
        "has_article": any(
            value.lower() in {"article", "blogposting"}
            for value in types
        ),
    }


def check_article(url: str) -> dict[str, Any]:
    response = fetch(url)
    page = soup(response.text)
    text = page.get_text(" ", strip=True)

    title = page.find("h1")

    meta_description = page.find(
        "meta",
        attrs={
            "name": re.compile("^description$", re.I),
        },
    )

    canonical = page.find(
        "link",
        attrs={
            "rel": lambda value: (
                value and "canonical" in value
            ),
        },
    )

    images = page.select("main img, article img")

    tags = page.select(
        ".tags a, [class*='tag' i] a"
    )

    related = page.select(
        ".related, [class*='related' i]"
    )

    h2_count = len(page.select("h2"))

    image_credit = (
        "image credits" in text.lower()
        or "image attribution" in text.lower()
    )

    title_text = (
        title.get_text(" ", strip=True)
        if title else ""
    )

    capitalized = bool(
        title_text and title_text[0].isupper()
    )

    schema = check_json_ld(page)

    required_failures = []

    if not title:
        required_failures.append("title")

    if not meta_description:
        required_failures.append("description")

    if not images:
        required_failures.append("image")

    if not tags:
        required_failures.append("tags")

    if not schema["present"]:
        required_failures.append("schema")

    if not image_credit:
        required_failures.append("image credits")

    if not related:
        required_failures.append("related")

    if h2_count < GOLDEN["article"]["minimum_h2"]:
        required_failures.append("h2 structure")

    return {
        "url": url,
        "status": response.status_code,
        "title": title_text,
        "title_capitalized": capitalized,
        "meta_description": (
            meta_description.get(
                "content", ""
            ).strip()
            if meta_description else None
        ),
        "canonical": (
            canonical.get("href", "")
            if canonical else None
        ),
        "images": len(images),
        "tags": len(tags),
        "h2_count": h2_count,
        "image_credits": image_credit,
        "related": bool(related),
        "schema": schema,
        "required_failures": required_failures,
        "html_length": len(response.text),
    }


def responsive_checks(
    home_html: str,
) -> dict[str, Any]:
    page = soup(home_html)

    style_text = "\n".join(
        style.get_text()
        for style in page.select("style")
    )

    stylesheet_urls = [
        urljoin(SITE_URL, link.get("href"))
        for link in page.select(
            'link[rel="stylesheet"][href]'
        )
    ]

    media_query = bool(
        re.search(r"@media", style_text, re.I)
    )

    mobile_units = bool(
        re.search(
            r"(rem|em|vw|vh|clamp)\b",
            style_text,
            re.I,
        )
    )

    overflow_hidden = bool(
        re.search(
            r"overflow-x\s*:\s*hidden",
            style_text,
            re.I,
        )
    )

    return {
        "inline_media_queries": media_query,
        "responsive_units": mobile_units,
        "overflow_x_hidden": overflow_hidden,
        "stylesheet_count": len(stylesheet_urls),
        "stylesheet_urls": stylesheet_urls,
    }


def generate_suggestions(
    report: dict[str, Any],
) -> list[dict[str, Any]]:
    suggestions = []

    home = report["home"]

    if not home["viewport"]:
        suggestions.append({
            "priority": "high",
            "area": "mobile",
            "suggestion": "Add a responsive viewport meta tag.",
        })

    if not home["search"]:
        suggestions.append({
            "priority": "high",
            "area": "search",
            "suggestion": "Ensure the search control is present and usable.",
        })

    if not home["hero"]:
        suggestions.append({
            "priority": "medium",
            "area": "hero",
            "suggestion": "Restore a clearly identifiable hero section.",
        })

    if home["article_cards"] < 6:
        suggestions.append({
            "priority": "medium",
            "area": "grid",
            "suggestion": "Ensure the homepage grid exposes enough article cards.",
        })

    for article in report["articles"]:
        for failure in article["required_failures"]:
            suggestions.append({
                "priority": (
                    "high" if failure in {
                        "title",
                        "description",
                        "schema",
                    } else "medium"
                ),
                "area": failure,
                "url": article["url"],
                "suggestion": (
                    f"Fix article-level {failure} consistency."
                ),
            })

    responsive = report["responsive"]

    if (
        not responsive["inline_media_queries"]
        and not responsive["stylesheet_count"]
    ):
        suggestions.append({
            "priority": "high",
            "area": "responsive",
            "suggestion": "Add or restore responsive CSS for mobile layouts.",
        })

    return suggestions


def main() -> int:
    ensure_logs()

    report: dict[str, Any] = {
        "timestamp": now(),
        "site": SITE_URL,
        "golden": GOLDEN,
        "home": {},
        "articles": [],
        "responsive": {},
        "status": "unknown",
    }

    try:
        response = fetch(SITE_URL)

        if not response.ok:
            raise RuntimeError(
                f"Homepage returned {response.status_code}"
            )

        home_html = response.text

        report["home"] = check_home()

        article_urls = extract_article_urls(home_html)

        report["articles"] = [
            check_article(url) for url in article_urls
        ]

        report["responsive"] = responsive_checks(home_html)

        suggestions = generate_suggestions(report)

        failures = []
        failures.extend(
            report["home"].get("missing_text", [])
        )

        for article in report["articles"]:
            failures.extend(article["required_failures"])

        report["status"] = (
            "healthy" if not failures
            else "needs_attention"
        )

        report["failure_count"] = len(failures)

        SUGGESTIONS_PATH.write_text(
            json.dumps(
                {
                    "timestamp": now(),
                    "suggestions": suggestions,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        REPORT_PATH.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            )
        )

        return 0

    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)

        REPORT_PATH.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
