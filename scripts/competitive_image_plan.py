#!/usr/bin/env python3

import json
import re
import sys

from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"

IMAGE_COUNT = 10
MAX_HEADING_QUERY_WORDS = 4


def load_article() -> Dict[str, Any]:
    if not ARTICLE_PATH.exists():
        raise FileNotFoundError(
            f"article.json was not found at: {ARTICLE_PATH}"
        )

    try:
        with ARTICLE_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            article = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"article.json contains invalid JSON: {exc}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Could not read article.json: {exc}"
        ) from exc

    if not isinstance(article, dict):
        raise ValueError(
            "article.json must contain a JSON object."
        )

    return article


def save_article(article: Dict[str, Any]) -> None:
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")

    try:
        with temp_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                article,
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.write("\n")

        temp_path.replace(ARTICLE_PATH)

    except OSError as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        raise RuntimeError(
            f"Could not save article.json: {exc}"
        ) from exc


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""

    value = value.replace("\r", " ")
    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def extract_h2_headings(
    content: str,
) -> List[str]:
    headings: List[str] = []

    in_fenced_code_block = False
    fence_marker: Optional[str] = None

    for line in content.splitlines():
        stripped = line.strip()

        if (
            stripped.startswith("```")
            or stripped.startswith("~~~")
        ):
            if not in_fenced_code_block:
                in_fenced_code_block = True

                if stripped.startswith("```"):
                    fence_marker = "```"
                else:
                    fence_marker = "~~~"

            elif (
                fence_marker
                and stripped.startswith(
                    fence_marker
                )
            ):
                in_fenced_code_block = False
                fence_marker = None

            continue

        if in_fenced_code_block:
            continue

        match = re.match(
            r"^\s*##[ \t]+([^#].*?)\s*$",
            line,
        )

        if not match:
            continue

        heading = clean_text(
            match.group(1)
        )

        if heading:
            headings.append(heading)

    return headings


def remove_markdown(text: str) -> str:
    text = re.sub(
        r"!\[[^\]]*\]\([^)]*\)",
        " ",
        text,
    )
    text = re.sub(
        r"\[[^\]]*\]\([^)]*\)",
        " ",
        text,
    )
    text = re.sub(
        r"`[^`]+`",
        " ",
        text,
    )
    text = re.sub(
        r"#{1,6}[ \t]+",
        " ",
        text,
    )
    text = re.sub(
        r"[*_~]+",
        " ",
        text,
    )

    return clean_text(text)


def extract_useful_terms(
    content: str,
) -> List[str]:
    stop_words = {
        "the", "and", "for", "with", "from",
        "that", "this", "your", "you", "are",
        "into", "without", "small", "home",
        "ideas", "tips", "guide", "best", "ways",
        "how", "what", "when", "where", "using",
        "use", "make", "get", "can", "more",
        "room", "space", "before", "after",
        "about", "their", "there", "these",
        "those", "than", "then", "also", "just",
        "yourself", "each", "every", "some",
        "very", "have", "has", "will", "should",
        "could", "would", "other", "which",
        "while", "only", "through", "because",
        "made",
    }

    words = re.findall(
        r"[A-Za-z][A-Za-z'-]{2,}",
        content,
    )

    result = []

    for word in words:
        normalized = word.lower()

        if normalized in stop_words:
            continue

        if normalized in result:
            continue

        result.append(normalized)

    return result


def normalize_query(value: str) -> str:
    value = clean_text(value)
    value = value.replace(
        "&",
        "and",
    )
    value = re.sub(
        r"[^A-Za-z0-9,\- ]+",
        " ",
        value,
    )
    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def shorten_heading(
    heading: str,
    maximum_words: int = MAX_HEADING_QUERY_WORDS,
) -> str:
    words = heading.split()

    if len(words) <= maximum_words:
        return heading

    return " ".join(
        words[:maximum_words]
    )


def compact_keyword(
    keyword: str,
) -> str:
    words = [
        word
        for word in keyword.split()
        if word.strip()
    ]

    if len(words) <= 3:
        return keyword

    return " ".join(words[:3])


def build_query_from_heading(
    heading: str,
    keyword: str,
    index: int,
) -> str:
    heading_clean = shorten_heading(
        clean_text(heading)
    )
    keyword_clean = compact_keyword(
        clean_text(keyword)
    )

    if index == 1:
        parts = [
            keyword_clean,
            "organized home interior",
        ]
    elif heading_clean:
        parts = [
            heading_clean,
            keyword_clean,
            "home interior",
        ]
    else:
        parts = [
            keyword_clean,
            "home organization",
            "interior",
        ]

    query = " ".join(
        part for part in parts if part
    )

    return normalize_query(query)


def build_fallback_queries(
    article: Dict[str, Any],
) -> List[str]:
    keyword = clean_text(
        article.get(
            "keyword",
            "",
        )
    )

    title = clean_text(
        article.get(
            "title",
            "",
        )
    )

    content = remove_markdown(
        clean_text(
            article.get(
                "content_markdown",
                "",
            )
        )
    )

    terms = extract_useful_terms(
        " ".join(
            [
                title,
                keyword,
                content,
            ]
        )
    )

    fallback_templates = [
        "modern home organization interior",
        "organized storage shelves home",
        "small space storage interior",
        "stylish home storage ideas",
        "decluttered organized room",
        "practical storage solution interior",
        "minimal organized home",
        "functional storage furniture",
        "space saving organization",
        "clean modern organized room",
    ]

    queries = []

    compact_keyword_value = (
        compact_keyword(keyword)
    )

    if compact_keyword_value:
        queries.append(
            normalize_query(
                f"{compact_keyword_value} "
                f"modern interior"
            )
        )

    for term in terms:
        if len(queries) >= IMAGE_COUNT:
            break

        if term in {
            "organization",
            "organized",
            "storage",
            "interior",
            "home",
            "room",
        }:
            continue

        query = normalize_query(
            f"{term} "
            f"home organization interior"
        )

        if query:
            queries.append(query)

    for template in fallback_templates:
        if len(queries) >= IMAGE_COUNT:
            break

        queries.append(
            normalize_query(template)
        )

    return queries


def make_unique(
    queries: List[str],
) -> List[str]:
    result = []
    seen = set()

    for query in queries:
        normalized = normalize_query(
            query
        )

        if not normalized:
            continue

        key = normalized.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(normalized)

    return result


def build_image_queries(
    article: Dict[str, Any],
) -> List[str]:
    content = article.get(
        "content_markdown",
        "",
    )

    if not isinstance(content, str):
        raise ValueError(
            "article.json field "
            "'content_markdown' "
            "must be a string."
        )

    if not content.strip():
        raise ValueError(
            "article.json contains empty "
            "content_markdown."
        )

    keyword = clean_text(
        article.get(
            "keyword",
            "",
        )
    )

    headings = extract_h2_headings(
        content
    )

    queries = []

    for index, heading in enumerate(
        headings,
        start=1,
    ):
        if len(queries) >= IMAGE_COUNT:
            break

        query = build_query_from_heading(
            heading,
            keyword,
            index,
        )

        if query:
            queries.append(query)

    queries = make_unique(queries)

    if len(queries) < IMAGE_COUNT:
        fallback_queries = (
            build_fallback_queries(article)
        )

        queries = make_unique(
            queries + fallback_queries
        )

    if len(queries) < IMAGE_COUNT:
        raise ValueError(
            "Could not generate exactly "
            f"{IMAGE_COUNT} unique image "
            "queries. "
            f"Generated {len(queries)}."
        )

    return queries[:IMAGE_COUNT]


def validate_queries(
    queries: List[str],
) -> None:
    if len(queries) != IMAGE_COUNT:
        raise ValueError(
            f"Expected exactly {IMAGE_COUNT} "
            f"image queries, got "
            f"{len(queries)}."
        )

    normalized = []

    for index, query in enumerate(
        queries,
        start=1,
    ):
        if not isinstance(query, str):
            raise ValueError(
                f"Image query #{index} "
                "must be a string."
            )

        query = normalize_query(query)

        if not query:
            raise ValueError(
                f"Image query #{index} "
                "is empty."
            )

        if query.lower() in normalized:
            raise ValueError(
                f"Image query #{index} "
                "is duplicated."
            )

        normalized.append(query.lower())


def main() -> int:
    print("=" * 70)
    print("COMPETITIVE IMAGE PLAN")
    print("=" * 70)

    try:
        article = load_article()

        title = clean_text(
            article.get(
                "title",
                "",
            )
        )

        keyword = clean_text(
            article.get(
                "keyword",
                "",
            )
        )

        content = article.get(
            "content_markdown",
            "",
        )

        if not title:
            raise ValueError(
                "article.json is missing "
                "'title'."
            )

        if not keyword:
            raise ValueError(
                "article.json is missing "
                "'keyword'."
            )

        if (
            not isinstance(content, str)
            or not content.strip()
        ):
            raise ValueError(
                "article.json is missing "
                "valid 'content_markdown'."
            )

        headings = extract_h2_headings(
            content
        )

        print(
            f"Article title: {title}"
        )
        print(
            f"Focus keyword: {keyword}"
        )
        print(
            f"H2 headings detected: "
            f"{len(headings)}"
        )

        queries = build_image_queries(
            article
        )

        validate_queries(queries)

        article["image_queries"] = (
            queries
        )

        save_article(article)

        print("")
        print("Generated image queries:")

        for index, query in enumerate(
            queries,
            start=1,
        ):
            if index == 1:
                label = "HERO"
            else:
                label = f"IMAGE {index}"

            print(f"{label}: {query}")

        print("")
        print(
            f"Saved {len(queries)} "
            "image queries "
            f"to {ARTICLE_PATH}"
        )

        print("=" * 70)
        print(
            "COMPETITIVE IMAGE PLAN "
            "COMPLETE"
        )
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print(
            "",
            file=sys.stderr,
        )
        print(
            "Operation cancelled.",
            file=sys.stderr,
        )
        return 130

    except Exception as exc:
        print(
            "",
            file=sys.stderr,
        )
        print(
            "COMPETITIVE IMAGE PLAN "
            "FAILED",
            file=sys.stderr,
        )
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
