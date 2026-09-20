#!/usr/bin/env python3

import os
import sys
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from groq import Groq


ROOT_DIR = Path(__file__).resolve().parents[1]
KEYWORDS_PATH = ROOT_DIR / "keywords.csv"
ARTICLE_PATH = ROOT_DIR / "article.json"

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "llama-3.3-70b-versatile",
)

MAX_RETRIES = 5
REQUEST_TIMEOUT = 120

MIN_WORDS = 1200
MAX_WORDS = 1900


def find_column(fieldnames, candidates):
    if not fieldnames:
        return None
    normalized = {
        str(name).strip().lower(): name
        for name in fieldnames
        if name is not None
    }
    for candidate in candidates:
        key = str(candidate).strip().lower()
        if key in normalized:
            return normalized[key]
    return None


def load_keywords():
    if not KEYWORDS_PATH.exists():
        raise FileNotFoundError(
            f"Keywords file not found: {KEYWORDS_PATH}"
        )
    with KEYWORDS_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError(
                "keywords.csv does not contain a header row."
            )
        rows = list(reader)

    keyword_col = find_column(
        fieldnames,
        ["keyword", "keywords", "focus_keyword",
         "focus keyword", "query"],
    )
    status_col = find_column(
        fieldnames,
        ["status", "state"],
    )
    if not keyword_col:
        raise ValueError(
            "Could not find a keyword column in keywords.csv."
        )
    if not status_col:
        raise ValueError(
            "Could not find a status column in keywords.csv."
        )
    return (rows, fieldnames, keyword_col, status_col)


def save_keywords(rows, fieldnames):
    temp_path = KEYWORDS_PATH.with_suffix(".csv.tmp")
    with temp_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(KEYWORDS_PATH)


def get_first_pending_keyword():
    (rows, fieldnames, keyword_col, status_col) = load_keywords()
    for row in rows:
        keyword = str(row.get(keyword_col, "")).strip()
        status = str(
            row.get(status_col, "")
        ).strip().lower()
        if keyword and status == "pending":
            return (
                keyword, rows, fieldnames,
                keyword_col, status_col,
            )
    raise RuntimeError(
        "No pending keyword was found in keywords.csv."
    )


def mark_keyword_processing(
    keyword, rows, fieldnames,
    keyword_col, status_col,
):
    found = False
    for row in rows:
        current_keyword = str(
            row.get(keyword_col, "")
        ).strip()
        if current_keyword == keyword:
            row[status_col] = "processing"
            found = True
            break
    if not found:
        raise ValueError(
            f"Keyword not found: {keyword}"
        )
    save_keywords(rows, fieldnames)


def mark_keyword_pending(keyword):
    (rows, fieldnames, keyword_col, status_col) = load_keywords()
    found = False
    for row in rows:
        current_keyword = str(
            row.get(keyword_col, "")
        ).strip()
        if current_keyword == keyword:
            row[status_col] = "pending"
            found = True
            break
    if not found:
        raise ValueError(
            f"Keyword not found: {keyword}"
        )
    save_keywords(rows, fieldnames)


def slugify(text):
    text = str(text).strip().lower()
    text = re.sub(
        r"[^\w\s-]", "", text, flags=re.UNICODE
    )
    text = re.sub(r"[-\s]+", "-", text)
    text = text.strip("-")
    return text


def get_exception_status_code(exc):
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(
            response, "status_code", None
        )
        if status_code is not None:
            return status_code
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return status_code
    return None


def extract_json_from_response(response_text):
    if not isinstance(response_text, str):
        raise ValueError(
            "Groq response content is not a string."
        )
    text = response_text.strip()
    if not text:
        raise ValueError(
            "Groq returned an empty response."
        )
    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*",
            "", text, flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\s*```$", "", text,
        ).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(
                "Could not find a valid JSON object."
            )
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Groq returned invalid JSON: {exc}"
            ) from exc


def generate_with_groq(api_key, keyword):
    client = Groq(api_key=api_key)

    system_prompt = """
You are an expert SEO content writer for an English-language website
about Home Organization and Small-Space Living.

Return ONLY a valid JSON object with exactly these fields:

{
  "title": "string",
  "meta_description": "string",
  "content_markdown": "string",
  "image_query": "string",
  "tags": ["string", "string"]
}

Requirements:
- Natural, clear American English.
- Approximately 1500 words (between 1200 and 1900).
- Focus keyword must appear in the title.
- Focus keyword must appear in the introduction.
- Use multiple H2 headings (Markdown ## syntax).
- No H1 heading.
- No YAML or TOML frontmatter.
- Practical, specific advice.
- No fake statistics, studies, or quotes.
- No AI mention.
- No placeholders like [insert], TODO, TBD.
- Meta description: 140-160 characters.
- image_query: short English Pexels search phrase.
- tags: 3-8 concise relevant tags.
- No Markdown code fences around the JSON.
""".strip()

    user_prompt = f"""
Write a complete blog article targeting this focus keyword:

{keyword}

Niche: Home Organization & Small-Space Living.
Use the exact focus keyword naturally in the title and introduction.
Return only the required JSON object.
""".strip()

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Calling Groq (attempt {attempt}/{MAX_RETRIES})..."
            )
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=5000,
                response_format={"type": "json_object"},
            )
            if not response.choices:
                raise ValueError(
                    "Groq returned no choices."
                )
            message = response.choices[0].message
            content = getattr(message, "content", None)
            if not content:
                raise ValueError(
                    "Groq returned an empty message."
                )
            generated = extract_json_from_response(content)
            if not isinstance(generated, dict):
                raise ValueError(
                    "Groq JSON response is not an object."
                )
            return generated

        except Exception as exc:
            last_exception = exc
            status_code = get_exception_status_code(exc)
            retryable = {429, 500, 502, 503, 504}

            if status_code is not None and status_code not in retryable:
                break
            if attempt >= MAX_RETRIES:
                break

            delay = min(2 ** (attempt - 1), 30)
            print(
                f"Groq request failed: {exc}",
                file=sys.stderr,
            )
            print(f"Retrying in {delay} seconds...")
            time.sleep(delay)

    raise RuntimeError(
        f"Groq generation failed after "
        f"{MAX_RETRIES} attempts: {last_exception}"
    )

def require_string(data, field_name):
    value = data.get(field_name)
    if not isinstance(value, str):
        raise ValueError(
            f"Generated field '{field_name}' must be a string."
        )
    value = value.strip()
    if not value:
        raise ValueError(
            f"Generated field '{field_name}' is empty."
        )
    return value


def extract_generated_fields(generated):
    title = require_string(generated, "title")
    meta_description = require_string(
        generated, "meta_description"
    )
    content_markdown = require_string(
        generated, "content_markdown"
    )
    image_query = require_string(
        generated, "image_query"
    )

    raw_tags = generated.get("tags")
    if not isinstance(raw_tags, list):
        raise ValueError(
            "Generated field 'tags' must be a list."
        )

    tags = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if tag and tag not in tags:
            tags.append(tag)

    if not tags:
        raise ValueError(
            "Generated tags list is empty."
        )

    return (
        title,
        meta_description,
        content_markdown,
        image_query,
        tags,
    )


def clean_markdown(content):
    content = str(content).strip()

    content = re.sub(
        r"^```(?:markdown|md)?\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)
    content = re.sub(
        r"^\s*#\s+.+?\n+",
        "",
        content,
        count=1,
    )

    return content.strip()


def count_words(text: str) -> int:
    plain_text = re.sub(
        r"[!\[\]()]+",
        " ",
        text,
    )
    plain_text = re.sub(
        r"`[^`]+`",
        "",
        plain_text,
    )
    words = re.findall(
        r"\b[\w'-]+\b",
        plain_text,
        flags=re.UNICODE,
    )
    return len(words)


def validate_generated_content(
    keyword,
    title,
    meta_description,
    content_markdown,
    image_query,
    tags,
):
    errors = []

    keyword = str(keyword).strip()
    title = str(title).strip()
    meta_description = str(meta_description).strip()
    content_markdown = str(content_markdown).strip()
    image_query = str(image_query).strip()

    if not keyword:
        errors.append("Focus keyword is empty.")
    if not title:
        errors.append("Title is empty.")
    if not meta_description:
        errors.append("Meta description is empty.")
    if not content_markdown:
        errors.append("Content is empty.")
    if not image_query:
        errors.append("Image query is empty.")
    if not isinstance(tags, list) or not tags:
        errors.append("Tags must be a non-empty list.")

    title_length = len(title)
    if title_length < 30:
        errors.append(
            f"Title is too short: {title_length} characters. "
            "Minimum is 30."
        )
    elif title_length > 65:
        errors.append(
            f"Title is too long: {title_length} characters. "
            "Maximum is 65."
        )

    meta_length = len(meta_description)
    if meta_length < 140:
        errors.append(
            "Meta description is too short: "
            f"{meta_length} characters. Minimum is 140."
        )
    elif meta_length > 160:
        errors.append(
            "Meta description is too long: "
            f"{meta_length} characters. Maximum is 160."
        )

    if keyword:
        keyword_lower = keyword.lower()
        if keyword_lower not in title.lower():
            errors.append(
                "Focus keyword is not present in the title."
            )
        introduction = content_markdown[:1200].lower()
        if keyword_lower not in introduction:
            errors.append(
                "Focus keyword is not present in the introduction."
            )

    h2_pattern = re.compile(
        r"^\s*##\s+\S+",
        flags=re.MULTILINE,
    )
    if not h2_pattern.search(content_markdown):
        errors.append(
            "Article does not contain an H2 heading."
        )

    placeholder_patterns = [
        r"\[insert[^\]]*\]",
        r"\[INSERT[^\]]*\]",
        r"\bTODO\b",
        r"\bTBD\b",
        r"\bPLACEHOLDER\b",
        r"\bLOREM\s+IPSUM\b",
        r"<insert[^>]*>",
        r"\{\{[^}]+\}\}",
        r"\[\s*your\s+[^]]+\]",
        r"\[\s*add\s+[^]]+\]",
        r"\[\s*replace\s+[^]]+\]",
    ]

    for pattern in placeholder_patterns:
        if re.search(
            pattern,
            content_markdown,
            flags=re.IGNORECASE,
        ):
            errors.append(
                "Article contains a placeholder or unfinished text."
            )
            break

    words = count_words(content_markdown)
    if words < MIN_WORDS:
        errors.append(
            f"Article is too short: {words} words. "
            f"Minimum allowed is {MIN_WORDS}."
        )
    elif words > MAX_WORDS:
        errors.append(
            f"Article is too long: {words} words. "
            f"Maximum allowed is {MAX_WORDS}."
        )

    return errors


def save_article(article):
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")
    with temp_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as file:
        json.dump(
            article,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")
    temp_path.replace(ARTICLE_PATH)


def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print(
            "ERROR: GROQ_API_KEY environment variable is not set.",
            file=sys.stderr,
        )
        return 1

    try:
        (
            keyword,
            rows,
            fieldnames,
            keyword_col,
            status_col,
        ) = get_first_pending_keyword()
    except Exception as exc:
        print(
            f"ERROR: Could not load keywords.csv: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"Selected keyword: {keyword}")

    try:
        mark_keyword_processing(
            keyword,
            rows,
            fieldnames,
            keyword_col,
            status_col,
        )
        print("Keyword status changed to: processing")
    except Exception as exc:
        print(
            "ERROR: Could not mark keyword as processing: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1

    try:
        generated = generate_with_groq(api_key, keyword)

        (
            title,
            meta_description,
            content_markdown,
            image_query,
            tags,
        ) = extract_generated_fields(generated)

        title = title.strip()
        meta_description = meta_description.strip()
        content_markdown = clean_markdown(content_markdown)
        image_query = image_query.strip()

        normalized_tags = []
        for tag in tags:
            tag = str(tag).strip()
            if tag and tag not in normalized_tags:
                normalized_tags.append(tag)
        tags = normalized_tags

        slug = slugify(title)
        if not slug:
            raise ValueError(
                "Generated title produced an empty slug."
            )

        errors = validate_generated_content(
            keyword,
            title,
            meta_description,
            content_markdown,
            image_query,
            tags,
        )

        if errors:
            error_text = "\n".join(
                f"- {error}" for error in errors
            )
            raise ValueError(
                "Generated article failed validation:\n"
                f"{error_text}"
            )

        word_count = count_words(content_markdown)

        article = {
            "keyword": keyword,
            "title": title,
            "slug": slug,
            "meta_description": meta_description,
            "content_markdown": content_markdown,
            "image_query": image_query,
            "tags": tags,
            "word_count": word_count,
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        save_article(article)

        print("")
        print("Article generated successfully.")
        print(f"Keyword: {keyword}")
        print(f"Title: {title}")
        print(f"Slug: {slug}")
        print(f"Word count: {word_count}")
        print(f"Tags: {', '.join(tags)}")
        print(f"Saved to: {ARTICLE_PATH}")

        return 0

    except Exception as exc:
        print(
            f"ERROR: Article generation failed: {exc}",
            file=sys.stderr,
        )
        try:
            mark_keyword_pending(keyword)
            print(
                f"Keyword returned to pending: {keyword}"
            )
        except Exception as reset_exc:
            print(
                "ERROR: Could not return keyword to pending: "
                f"{reset_exc}",
                file=sys.stderr,
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
