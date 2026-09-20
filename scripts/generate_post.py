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

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_RETRIES = 5
MIN_WORDS = 1000
MAX_WORDS = 2500


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
        "r", encoding="utf-8-sig", newline=""
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
    status_col = find_column(fieldnames, ["status", "state"])

    if not keyword_col:
        raise ValueError("Could not find keyword column.")
    if not status_col:
        raise ValueError("Could not find status column.")

    return (rows, fieldnames, keyword_col, status_col)


def save_keywords(rows, fieldnames):
    temp_path = KEYWORDS_PATH.with_suffix(".csv.tmp")
    with temp_path.open(
        "w", encoding="utf-8", newline=""
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=fieldnames, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(KEYWORDS_PATH)


def get_first_pending_keyword():
    rows, fieldnames, keyword_col, status_col = load_keywords()
    for row in rows:
        keyword = str(row.get(keyword_col, "")).strip()
        status = str(row.get(status_col, "")).strip().lower()
        if keyword and status == "pending":
            return (
                keyword, rows, fieldnames,
                keyword_col, status_col,
            )
    raise RuntimeError("No pending keyword found.")


def mark_keyword_processing(
    keyword, rows, fieldnames, keyword_col, status_col,
):
    found = False
    for row in rows:
        if str(row.get(keyword_col, "")).strip() == keyword:
            row[status_col] = "processing"
            found = True
            break
    if not found:
        raise ValueError(f"Keyword not found: {keyword}")
    save_keywords(rows, fieldnames)


def mark_keyword_pending(keyword):
    rows, fieldnames, keyword_col, status_col = load_keywords()
    for row in rows:
        if str(row.get(keyword_col, "")).strip() == keyword:
            row[status_col] = "pending"
            break
    save_keywords(rows, fieldnames)


def slugify(text):
    text = str(text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", " ", text).strip()
    words = text.split()[:6]
    slug = "-".join(words)
    if len(slug) <= 40:
        return slug
    shortened = []
    for word in words:
        candidate = word if not shortened else "-".join(shortened + [word])
        if len(candidate) > 40:
            break
        shortened.append(word)
    return "-".join(shortened).strip("-")


def get_exception_status_code(exc):
    response = getattr(exc, "response", None)
    if response is not None:
        code = getattr(response, "status_code", None)
        if code is not None:
            return code
    code = getattr(exc, "status_code", None)
    return code


def extract_json_from_response(response_text):
    if not isinstance(response_text, str):
        raise ValueError("Response is not a string.")
    text = response_text.strip()
    if not text:
        raise ValueError("Empty response.")
    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE
        )
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found.")
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc


def generate_with_groq(api_key, keyword):
    client = Groq(api_key=api_key)

    system_prompt = """
You are an expert long-form SEO content writer for an English-language website about Home Organization and Small-Space Living.

Your task is to create ONE complete, genuinely useful, original blog article.

IMPORTANT LENGTH REQUIREMENT:
The article MUST contain between 1500 and 1800 words of actual content.
Do NOT produce a short article.
Do NOT stop after a few sections.
Do NOT summarize the topic instead of writing the full article.

Before finishing, internally check that the article contains approximately 1500-1800 words. If it is below 1500 words, continue writing additional useful sections until it reaches the required length.

Return ONLY a valid JSON object.

The JSON object must contain exactly these fields:

{
  "title": "string",
  "meta_description": "string",
  "content_markdown": "string",
  "image_query": "string",
  "tags": ["string", "string"]
}

ARTICLE REQUIREMENTS:
- Write in natural, clear American English.
- Target approximately 1500-1800 words.
- NEVER intentionally write fewer than 1500 words.
- Use useful Markdown H2 headings with: ## Heading
- Use H3 headings where they genuinely improve organization.
- Do not use an H1 heading inside content_markdown.
- Do not include YAML or TOML frontmatter.
- Include a useful introduction.
- Include practical, specific advice.
- Include concrete examples where useful.
- Avoid repetitive filler.
- Avoid generic one-sentence sections.
- End with a useful conclusion or actionable takeaway.
- The focus keyword must appear naturally in the title.
- The focus keyword must appear naturally in the introduction.
- Use the focus keyword naturally throughout without keyword stuffing.
- The meta description must be approximately 140-160 characters.
- image_query must be a concise English search phrase for Pexels.
- tags must contain 3-8 concise tags.
- Do not invent statistics, studies, quotes, or citations.
- Do not use placeholders.
- Do not mention that the article was generated by AI.
- Do not include Markdown code fences around the JSON.
- Ensure the final response is valid JSON.
""".strip()

    user_prompt = f"""
Write a complete long-form SEO blog article targeting this focus keyword:

{keyword}

Website niche:
Home Organization & Small-Space Living

The article MUST be 1500-1800 words.

Do not return a short answer, outline, summary, or abbreviated article.

Build the article with:
- A strong introduction
- Multiple detailed H2 sections
- Practical step-by-step advice
- Specific examples relevant to small homes and apartments
- Useful organization strategies
- Common mistakes or considerations
- A practical conclusion

Use the exact focus keyword naturally in the title and introduction.

Before returning the JSON, verify internally that the article is at least 1500 words. If shorter, expand with additional useful sections.

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
                max_tokens=12000,
                response_format={"type": "json_object"},
            )
            if not response.choices:
                raise ValueError("No choices returned.")
            content = getattr(response.choices[0].message, "content", None)
            if not content:
                raise ValueError("Empty message.")
            generated = extract_json_from_response(content)
            if not isinstance(generated, dict):
                raise ValueError("Not a JSON object.")
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
            print(f"Groq failed: {exc}", file=sys.stderr)
            print(f"Retry in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(
        f"Groq failed after {MAX_RETRIES} attempts: {last_exception}"
    )


def require_string(data, field_name):
    value = data.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' must be a string.")
    value = value.strip()
    if not value:
        raise ValueError(f"'{field_name}' is empty.")
    return value


def extract_generated_fields(generated):
    title = require_string(generated, "title")
    meta_description = require_string(generated, "meta_description")
    content_markdown = require_string(generated, "content_markdown")
    image_query = require_string(generated, "image_query")

    raw_tags = generated.get("tags")
    if not isinstance(raw_tags, list):
        raise ValueError("'tags' must be a list.")

    tags = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if tag and tag not in tags:
            tags.append(tag)

    if not tags:
        raise ValueError("Tags list is empty.")

    return (title, meta_description, content_markdown, image_query, tags)


def clean_markdown(content):
    content = str(content).strip()
    content = re.sub(
        r"^```(?:markdown|md)?\s*", "",
        content, flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)
    content = re.sub(r"^\s*#\s+.+?\n+", "", content, count=1)
    return content.strip()


def count_words(text: str) -> int:
    plain = re.sub(r"[!\[\]()]+", " ", text)
    plain = re.sub(r"`[^`]+`", "", plain)
    return len(re.findall(r"\b[\w'-]+\b", plain, flags=re.UNICODE))


def validate_generated_content(
    keyword, title, meta_description,
    content_markdown, image_query, tags,
):
    errors = []

    if not keyword:
        errors.append("Keyword empty.")
    if not title:
        errors.append("Title empty.")
    if not meta_description:
        errors.append("Meta description empty.")
    if not content_markdown:
        errors.append("Content empty.")
    if not image_query:
        errors.append("Image query empty.")

    if keyword and keyword.lower() not in title.lower():
        errors.append("Keyword not in title.")

    if keyword:
        intro = content_markdown[:1500].lower()
        if keyword.lower() not in intro:
            errors.append("Keyword not in introduction.")

    if not re.search(r"^\s*##\s+\S+", content_markdown, re.MULTILINE):
        errors.append("No H2 heading.")

    words = count_words(content_markdown)
    if words < MIN_WORDS:
        errors.append(f"Too short: {words} words.")
    elif words > MAX_WORDS:
        errors.append(f"Too long: {words} words.")

    return errors


def save_article(article):
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(article, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temp_path.replace(ARTICLE_PATH)


def main():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY missing.", file=sys.stderr)
        return 1

    try:
        (
            keyword, rows, fieldnames,
            keyword_col, status_col,
        ) = get_first_pending_keyword()
    except Exception as exc:
        print(f"ERROR loading keywords: {exc}", file=sys.stderr)
        return 1

    print(f"Selected keyword: {keyword}")

    try:
        mark_keyword_processing(
            keyword, rows, fieldnames, keyword_col, status_col,
        )
        print("Keyword status changed to: processing")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        generated = generate_with_groq(api_key, keyword)

        (
            title, meta_description,
            content_markdown, image_query, tags,
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
            raise ValueError("Empty slug from title.")

        errors = validate_generated_content(
            keyword, title, meta_description,
            content_markdown, image_query, tags,
        )

        if errors:
            error_text = "\n".join(f"- {e}" for e in errors)
            print(
                f"WARNING: validation issues:\n{error_text}",
                file=sys.stderr,
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
            "generated_at": datetime.now(timezone.utc).isoformat(),
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
        print(f"ERROR: {exc}", file=sys.stderr)
        try:
            mark_keyword_pending(keyword)
            print(f"Keyword returned to pending: {keyword}")
        except Exception as reset_exc:
            print(f"ERROR resetting: {reset_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
