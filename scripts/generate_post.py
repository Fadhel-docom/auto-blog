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

    status_col = find_column(
        fieldnames, ["status", "state"]
    )

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
            file, fieldnames=fieldnames,
            extrasaction="ignore"
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
    stop_words = {
        "for", "to", "of", "the", "a", "an",
        "in", "on", "at", "and", "or", "with",
    }

    text = str(text).strip().lower()

    text = re.sub(
        r"[^\w\s-]", "", text, flags=re.UNICODE
    )

    text = re.sub(r"[-\s]+", "-", text).strip("-")

    words = text.split("-")

    while words and words[-1] in stop_words:
        words.pop()

    slug = "-".join(words).strip("-")

    if not slug:
        slug = "-".join(text.split("-")[:6]).strip("-")

    if len(slug) > 60:
        slug = slug[:60].rstrip("-")

    return slug


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
            r"^```(?:json)?\s*", "",
            text, flags=re.IGNORECASE,
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
            raise ValueError(
                f"Invalid JSON: {exc}"
            ) from exc


def pick_specific_angle(api_key, keyword):
    client = Groq(api_key=api_key)

    system_prompt = """
You are an expert editorial strategist for an English-language
website about Home Organization & Small-Space Living.

Your job is to turn broad SEO keywords into specific, useful,
practical article angles.

For the supplied keyword:

1. Generate exactly 5 distinct article angles.
2. Each angle must be substantially narrower and more specific
   than the original keyword.
3. Avoid generic angles such as:
   - "best ideas"
   - "complete guide"
   - "tips and tricks"
   unless they are narrowed to a clearly defined situation.
4. Prefer angles based on:
   - a specific room or zone
   - a specific storage problem
   - a specific type of small home
   - a specific constraint
   - a specific household situation
   - measurements or dimensions
   - renter-friendly limitations
   - a specific before/after problem
5. The angle should be specific enough that two writers using
   the same keyword would be unlikely to produce the same article.
6. The angle must still be useful to an ordinary homeowner or
   renter and must fit the site's Home Organization &
   Small-Space Living niche.
7. Do not invent statistics, studies, expert quotes, or factual
   claims.

After generating the five angles, select the SINGLE angle that
is the most specific, concrete, useful, and actionable.

Return ONLY valid JSON in exactly this structure:

{
  "angles": [
    "angle 1",
    "angle 2",
    "angle 3",
    "angle 4",
    "angle 5"
  ],
  "selected_angle": "the most specific angle"
}
""".strip()

    user_prompt = f"""
Focus keyword:

{keyword}

Generate exactly five narrow article angles for this keyword,
then select the most specific and actionable one.

Return only the required JSON object.
""".strip()

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Selecting article angle with Groq "
                f"(attempt {attempt}/{MAX_RETRIES})..."
            )

            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.6,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

            if not response.choices:
                raise ValueError("No choices returned.")

            content = getattr(
                response.choices[0].message, "content", None
            )

            if not content:
                raise ValueError("Empty message.")

            result = extract_json_from_response(content)

            if not isinstance(result, dict):
                raise ValueError(
                    "Angle response is not a JSON object."
                )

            raw_angles = result.get("angles")

            if not isinstance(raw_angles, list):
                raise ValueError("'angles' must be a list.")

            angles = []

            for angle in raw_angles:
                if not isinstance(angle, str):
                    continue
                angle = angle.strip()
                if angle and angle not in angles:
                    angles.append(angle)

            if len(angles) != 5:
                raise ValueError(
                    "Groq must return exactly 5 unique angles."
                )

            selected_angle = result.get("selected_angle")

            if not isinstance(selected_angle, str):
                raise ValueError(
                    "'selected_angle' must be a string."
                )

            selected_angle = selected_angle.strip()

            if not selected_angle:
                raise ValueError("'selected_angle' is empty.")

            if selected_angle not in angles:
                selected_angle = angles[0]

            print("Generated 5 article angles:")
            for index, angle in enumerate(angles, start=1):
                marker = (
                    "  <-- SELECTED"
                    if angle == selected_angle
                    else ""
                )
                print(f"{index}. {angle}{marker}")

            return selected_angle

        except Exception as exc:
            last_exception = exc
            status_code = get_exception_status_code(exc)
            retryable = {429, 500, 502, 503, 504}

            if (
                status_code is not None
                and status_code not in retryable
            ):
                break

            if attempt >= MAX_RETRIES:
                break

            delay = min(2 ** (attempt - 1), 30)
            print(
                f"Groq angle selection failed: {exc}",
                file=sys.stderr,
            )
            print(f"Retry in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(
        "Groq angle selection failed after "
        f"{MAX_RETRIES} attempts: {last_exception}"
    )


def generate_with_groq(api_key, keyword, specific_angle):
    client = Groq(api_key=api_key)

    system_prompt = """
You are an expert long-form SEO content writer and practical
home-organization editor for an English-language website about
Home Organization & Small-Space Living.

Your job is to create ONE genuinely useful, original article
that solves a specific reader problem.

EDITORIAL DIRECTION:
- Start from the supplied focus keyword.
- Build the entire article around the supplied specific angle.
- The specific angle is the central subject of the article.
- Do not broaden the article into a generic guide.

LENGTH:
- Write approximately 1500-1800 words of actual article content.
- Never intentionally produce a short article.
- Do not stop after a few sections.
- Before returning the JSON, internally verify the article length.

STRUCTURE:
- Use 5-7 useful H2 headings.
- Use H3 headings only when they genuinely improve organization.
- Do not use an H1 heading inside content_markdown.
- Use short paragraphs, generally 2-4 sentences.
- Use numbered steps when explaining a process.
- Use bullet lists when they improve readability.
- Use Markdown bold for genuinely important insights.
- Use blockquotes only when they add useful emphasis.
- End with a practical conclusion and a natural CTA.

CONTENT QUALITY:
- Give concrete, practical advice.
- Include 3-5 concrete examples relevant to real homes.
- Include useful measurements or dimensions where appropriate.
- Include common mistakes, trade-offs, or considerations.
- Include approximately 3 generic product recommendations
  without inventing brands, prices, or reviews.
- Avoid vague advice.
- Avoid repetitive tips.

SEO:
- The exact focus keyword must appear naturally in the title.
- The exact focus keyword must appear naturally in the introduction.
- Do not keyword-stuff.
- The meta description should be approximately 140-160 characters.

ACCURACY:
- Do not invent statistics, studies, quotes, or citations.
- Do not use placeholders.
- Do not mention AI generation.

IMAGES:
- Generate exactly 5 distinct image search queries.
- Each query must be a concise English phrase for Pexels.
- The five queries should represent different visual aspects.

OUTPUT:
Return ONLY one valid JSON object.

{
  "title": "string",
  "meta_description": "string",
  "content_markdown": "string",
  "image_queries": [
    "string", "string", "string", "string", "string"
  ],
  "tags": ["string", "string"]
}

Do not wrap the JSON in Markdown code fences.
""".strip()

    user_prompt = f"""
Write a complete long-form SEO article for the following
focus keyword:

{keyword}

SPECIFIC ARTICLE ANGLE:
{specific_angle}

Website niche:
Home Organization & Small-Space Living

The specific angle above is mandatory.
Do NOT write a generic article about "{keyword}".

The article must be approximately 1500-1800 words.

Use the exact focus keyword naturally in the title and
introduction.

Generate exactly 5 distinct Pexels image search queries.

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

            content = getattr(
                response.choices[0].message, "content", None
            )

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

            if (
                status_code is not None
                and status_code not in retryable
            ):
                break

            if attempt >= MAX_RETRIES:
                break

            delay = min(2 ** (attempt - 1), 30)
            print(f"Groq failed: {exc}", file=sys.stderr)
            print(f"Retry in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(
        f"Groq failed after {MAX_RETRIES} attempts: "
        f"{last_exception}"
    )


def require_string(data, field_name):
    value = data.get(field_name)

    if not isinstance(value, str):
        raise ValueError(
            f"'{field_name}' must be a string."
        )

    value = value.strip()

    if not value:
        raise ValueError(f"'{field_name}' is empty.")

    return value


def extract_generated_fields(generated):
    title = require_string(generated, "title")
    meta_description = require_string(
        generated, "meta_description"
    )
    content_markdown = require_string(
        generated, "content_markdown"
    )

    raw_image_queries = generated.get("image_queries")

    if not isinstance(raw_image_queries, list):
        raise ValueError("'image_queries' must be a list.")

    image_queries = []

    for query in raw_image_queries:
        if not isinstance(query, str):
            continue
        query = query.strip()
        if query and query not in image_queries:
            image_queries.append(query)

    if len(image_queries) != 5:
        raise ValueError(
            "'image_queries' must contain exactly 5 "
            "unique search queries."
        )

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

    return (
        title, meta_description,
        content_markdown, image_queries, tags,
    )


def clean_markdown(content):
    content = str(content).strip()

    content = re.sub(
        r"^```(?:markdown|md)?\s*", "",
        content, flags=re.IGNORECASE,
    )

    content = re.sub(r"\s*```$", "", content)

    content = re.sub(
        r"^\s*#\s+.+?\n+", "",
        content, count=1,
    )

    return content.strip()


def count_words(text: str) -> int:
    plain = re.sub(r"[!\[\]()]+", " ", text)
    plain = re.sub(r"`[^`]+`", "", plain)

    return len(
        re.findall(
            r"\b[\w'-]+\b", plain,
            flags=re.UNICODE,
        )
    )


def validate_generated_content(
    keyword, title, meta_description,
    content_markdown, image_queries, tags,
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

    if not isinstance(image_queries, list):
        errors.append("Image queries must be a list.")
    elif len(image_queries) != 5:
        errors.append(
            "Image queries must contain exactly 5 items."
        )

    if keyword and keyword.lower() not in title.lower():
        errors.append("Keyword not in title.")

    if keyword:
        intro = content_markdown[:1500].lower()
        if keyword.lower() not in intro:
            errors.append("Keyword not in introduction.")

    h2_count = len(
        re.findall(
            r"^\s*##\s+\S+",
            content_markdown,
            re.MULTILINE,
        )
    )

    if h2_count == 0:
        errors.append("No H2 heading.")
    elif h2_count < 5 or h2_count > 9:
        errors.append(
            f"Expected 5-9 H2 headings, found {h2_count}."
        )

    words = count_words(content_markdown)

    if words < MIN_WORDS:
        errors.append(f"Too short: {words} words.")
    elif words > MAX_WORDS:
        errors.append(f"Too long: {words} words.")

    if not isinstance(tags, list) or not tags:
        errors.append("Tags empty.")

    return errors


def save_article(article):
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")

    with temp_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as file:
        json.dump(
            article, file,
            ensure_ascii=False, indent=2,
        )
        file.write("\n")

    temp_path.replace(ARTICLE_PATH)


def main():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        print(
            "ERROR: GROQ_API_KEY missing.",
            file=sys.stderr,
        )
        return 1

    try:
        (
            keyword, rows, fieldnames,
            keyword_col, status_col,
        ) = get_first_pending_keyword()
    except Exception as exc:
        print(
            f"ERROR loading keywords: {exc}",
            file=sys.stderr,
        )
        return 1

    print(f"Selected keyword: {keyword}")

    try:
        mark_keyword_processing(
            keyword, rows, fieldnames,
            keyword_col, status_col,
        )
        print("Keyword status changed to: processing")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        specific_angle = pick_specific_angle(
            api_key, keyword
        )
        print(f"Selected specific angle: {specific_angle}")

        generated = generate_with_groq(
            api_key, keyword, specific_angle
        )

        (
            title, meta_description,
            content_markdown, image_queries, tags,
        ) = extract_generated_fields(generated)

        title = title.strip()
        meta_description = meta_description.strip()
        content_markdown = clean_markdown(content_markdown)

        normalized_image_queries = []
        for query in image_queries:
            query = str(query).strip()
            if query and query not in normalized_image_queries:
                normalized_image_queries.append(query)
        image_queries = normalized_image_queries

        normalized_tags = []
        for tag in tags:
            tag = str(tag).strip()
            if tag and tag not in normalized_tags:
                normalized_tags.append(tag)
        tags = normalized_tags

        if len(image_queries) != 5:
            raise ValueError(
                "Exactly 5 image queries are required."
            )

        slug = slugify(title)

        if not slug:
            raise ValueError("Empty slug from title.")

        errors = validate_generated_content(
            keyword, title, meta_description,
            content_markdown, image_queries, tags,
        )

        if errors:
            error_text = "\n".join(
                f"- {error}" for error in errors
            )
            print(
                f"WARNING: validation issues:\n{error_text}",
                file=sys.stderr,
            )

        word_count = count_words(content_markdown)

        article = {
            "keyword": keyword,
            "specific_angle": specific_angle,
            "title": title,
            "slug": slug,
            "meta_description": meta_description,
            "content_markdown": content_markdown,
            "image_queries": image_queries,
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
        print(f"Specific angle: {specific_angle}")
        print(f"Title: {title}")
        print(f"Slug: {slug}")
        print(f"Word count: {word_count}")
        print("Image queries:")
        for index, query in enumerate(
            image_queries, start=1
        ):
            print(f"  {index}. {query}")
        print(f"Tags: {', '.join(tags)}")
        print(f"Saved to: {ARTICLE_PATH}")

        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)

        try:
            mark_keyword_pending(keyword)
            print(
                f"Keyword returned to pending: {keyword}"
            )
        except Exception as reset_exc:
            print(
                f"ERROR resetting keyword status: "
                f"{reset_exc}",
                file=sys.stderr,
            )

        return 1


if __name__ == "__main__":
    sys.exit(main())
