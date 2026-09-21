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
        "r",
        encoding="utf-8-sig",
        newline=""
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
        [
            "keyword",
            "keywords",
            "focus_keyword",
            "focus keyword",
            "query",
        ],
    )

    status_col = find_column(
        fieldnames,
        ["status", "state"],
    )

    if not keyword_col:
        raise ValueError(
            "Could not find keyword column."
        )

    if not status_col:
        raise ValueError(
            "Could not find status column."
        )

    return (
        rows,
        fieldnames,
        keyword_col,
        status_col,
    )


def save_keywords(rows, fieldnames):
    temp_path = KEYWORDS_PATH.with_suffix(".csv.tmp")

    with temp_path.open(
        "w",
        encoding="utf-8",
        newline=""
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
    rows, fieldnames, keyword_col, status_col = load_keywords()

    for row in rows:
        keyword = str(
            row.get(keyword_col, "")
        ).strip()

        status = str(
            row.get(status_col, "")
        ).strip().lower()

        if keyword and status == "pending":
            return (
                keyword,
                rows,
                fieldnames,
                keyword_col,
                status_col,
            )

    raise RuntimeError(
        "No pending keyword found."
    )


def mark_keyword_processing(
    keyword,
    rows,
    fieldnames,
    keyword_col,
    status_col,
):
    found = False

    for row in rows:
        if (
            str(
                row.get(keyword_col, "")
            ).strip()
            == keyword
        ):
            row[status_col] = "processing"
            found = True
            break

    if not found:
        raise ValueError(
            f"Keyword not found: {keyword}"
        )

    save_keywords(
        rows,
        fieldnames,
    )


def mark_keyword_pending(keyword):
    rows, fieldnames, keyword_col, status_col = (
        load_keywords()
    )

    for row in rows:
        if (
            str(
                row.get(keyword_col, "")
            ).strip()
            == keyword
        ):
            row[status_col] = "pending"
            break

    save_keywords(
        rows,
        fieldnames,
    )


def slugify(text):
    stop_words = {
        "for", "to", "of", "the", "a", "an",
        "in", "on", "at", "and", "or", "with",
        "how", "your", "this", "that", "from", "into",
    }

    text = str(text).strip().lower()

    text = re.sub(
        r"[^\w\s-]",
        "",
        text,
        flags=re.UNICODE,
    )

    text = re.sub(
        r"[-\s]+",
        "-",
        text,
    ).strip("-")

    if not text:
        return ""

    raw_words = text.split("-")

    useful_words = []

    for word in raw_words:
        if not word:
            continue

        if word in stop_words:
            continue

        useful_words.append(word)

    if not useful_words:
        useful_words = raw_words[:6]

    selected_words = []

    for word in useful_words[:3]:
        selected_words.append(word)

    number_index = None

    for index, word in enumerate(useful_words):
        if re.search(r"\d", word):
            number_index = index
            break

    if number_index is not None:
        measurement_words = useful_words[
            number_index:number_index + 4
        ]

        for word in measurement_words:
            if word not in selected_words:
                selected_words.append(word)

    for word in useful_words:
        if word in selected_words:
            continue

        candidate_words = selected_words + [word]
        candidate = "-".join(candidate_words)

        if len(candidate) > 50:
            break

        selected_words.append(word)

        if len(selected_words) >= 7:
            break

    slug = "-".join(selected_words).strip("-")

    if len(slug) > 50:
        slug = slug[:50].rstrip("-")

    if not slug:
        slug = "-".join(
            text.split("-")[:6]
        ).strip("-")

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
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
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
                response.choices[0].message,
                "content",
                None,
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
                raise ValueError(
                    "'selected_angle' is empty."
                )

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
- DO NOT generate image queries in this step.
- Image queries will be generated in a separate step after
  the complete article and its H2 sections are available.

OUTPUT:
Return ONLY one valid JSON object.

{
  "title": "string",
  "meta_description": "string",
  "content_markdown": "string",
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

Do not generate image queries yet.

Return only the required JSON object.
""".strip()

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Calling Groq for article "
                f"(attempt {attempt}/{MAX_RETRIES})..."
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
                response.choices[0].message,
                "content",
                None,
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

            print(
                f"Groq article generation failed: {exc}",
                file=sys.stderr,
            )

            print(f"Retry in {delay}s...")

            time.sleep(delay)

    raise RuntimeError(
        f"Groq article generation failed after "
        f"{MAX_RETRIES} attempts: {last_exception}"
    )


def extract_h2_sections(content):
    lines = str(content).splitlines()
    sections = []
    current_heading = None
    current_body = []
    in_fenced_code_block = False
    fence_marker = None

    for line in lines:
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
                and stripped.startswith(fence_marker)
            ):
                in_fenced_code_block = False
                fence_marker = None

            if current_heading is not None:
                current_body.append(line)

            continue

        if not in_fenced_code_block:
            match = re.match(
                r"^\s*##[ \t]+([^#].*?)\s*$",
                line,
            )

            if match:
                if current_heading is not None:
                    sections.append(
                        {
                            "heading": current_heading,
                            "body": "\n".join(
                                current_body
                            ).strip(),
                        }
                    )

                current_heading = match.group(1).strip()
                current_body = []
                continue

        if current_heading is not None:
            current_body.append(line)

    if current_heading is not None:
        sections.append(
            {
                "heading": current_heading,
                "body": "\n".join(
                    current_body
                ).strip(),
            }
        )

    return sections


def generate_image_queries(api_key, title, content_markdown):
    sections = extract_h2_sections(content_markdown)

    if len(sections) < 4:
        raise ValueError(
            "At least 4 H2 sections are required "
            "to generate 5 image queries."
        )

    selected_sections = sections[:4]

    section_payload = []

    for index, section in enumerate(
        selected_sections,
        start=1,
    ):
        body = section["body"]

        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        section_payload.append(
            f"""
SECTION {index}

H2:
{section["heading"]}

SECTION CONTENT:
{body}
""".strip()
        )

    sections_text = "\n\n".join(section_payload)

    system_prompt = """
You are a professional visual content editor for an
English-language Home Organization & Small-Space Living website.

Your job is to create exactly 5 highly relevant Pexels search
queries AFTER reading a completed article.

QUERY STRUCTURE:

1. Hero query:
   - represents the overall article topic
   - should be visually specific

2. Section query #1:
   - represents H2 section 1 and its actual content

3. Section query #2:
   - represents H2 section 2 and its actual content

4. Section query #3:
   - represents H2 section 3 and its actual content

5. Section query #4:
   - represents H2 section 4 and its actual content

RULES:
- Return exactly 5 unique queries.
- Every query must be concise English.
- Every query must be suitable for Pexels.
- Prefer concrete visual objects, rooms, storage solutions,
  furniture, containers, layouts, or real-life scenes.
- Avoid abstract concepts.
- Avoid generic queries such as "home organization".
- Do not use photographer names.
- Do not use quotation marks around queries.
- The section queries must be meaningfully different from
  one another.
- The hero query must represent the article as a whole.

Return ONLY valid JSON:

{
  "image_queries": [
    "hero query",
    "H2 section 1 query",
    "H2 section 2 query",
    "H2 section 3 query",
    "H2 section 4 query"
  ]
}
""".strip()

    user_prompt = f"""
ARTICLE TITLE:
{title}

The complete article has been written already.

Use the article structure below to create image queries.

{sections_text}

Generate:
- 1 hero query for the overall article
- 1 query for each of the four supplied H2 sections

Return exactly 5 unique Pexels queries in the required JSON.
""".strip()

    client = Groq(api_key=api_key)

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Generating section-aware image queries "
                f"with Groq "
                f"(attempt {attempt}/{MAX_RETRIES})..."
            )

            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )

            if not response.choices:
                raise ValueError("No choices returned.")

            content = getattr(
                response.choices[0].message,
                "content",
                None,
            )

            if not content:
                raise ValueError(
                    "Empty image-query response."
                )

            result = extract_json_from_response(content)

            if not isinstance(result, dict):
                raise ValueError(
                    "Image-query response is not a JSON object."
                )

            raw_queries = result.get("image_queries")

            if not isinstance(raw_queries, list):
                raise ValueError(
                    "'image_queries' must be a list."
                )

            image_queries = []

            for query in raw_queries:
                if not isinstance(query, str):
                    continue

                query = query.strip()

                if query and query not in image_queries:
                    image_queries.append(query)

            if len(image_queries) != 5:
                raise ValueError(
                    "Groq must return exactly 5 unique "
                    "image queries."
                )

            print("Generated 5 section-aware image queries:")

            for index, query in enumerate(
                image_queries,
                start=1,
            ):
                if index == 1:
                    label = "HERO"
                else:
                    label = f"H2 #{index - 1}"

                print(f"  {index}. [{label}] {query}")

            return image_queries

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
                f"Groq image-query generation failed: {exc}",
                file=sys.stderr,
            )

            print(f"Retry in {delay}s...")

            time.sleep(delay)

    raise RuntimeError(
        "Groq image-query generation failed after "
        f"{MAX_RETRIES} attempts: {last_exception}"
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
        title,
        meta_description,
        content_markdown,
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
    plain = re.sub(r"[!\[\]()]+", " ", text)
    plain = re.sub(r"`[^`]+`", "", plain)

    return len(
        re.findall(
            r"\b[\w'-]+\b",
            plain,
            flags=re.UNICODE,
        )
    )


def validate_generated_content(
    keyword,
    title,
    meta_description,
    content_markdown,
    image_queries,
    tags,
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
        "w",
        encoding="utf-8",
        newline="\n"
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
            "ERROR: GROQ_API_KEY missing.",
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
            f"ERROR loading keywords: {exc}",
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
        print(f"ERROR: {exc}", file=sys.stderr)

        return 1

    try:
        specific_angle = pick_specific_angle(
            api_key,
            keyword,
        )

        print(
            f"Selected specific angle: {specific_angle}"
        )

        generated = generate_with_groq(
            api_key,
            keyword,
            specific_angle,
        )

        (
            title,
            meta_description,
            content_markdown,
            tags,
        ) = extract_generated_fields(generated)

        title = title.strip()
        meta_description = meta_description.strip()
        content_markdown = clean_markdown(content_markdown)

        normalized_tags = []

        for tag in tags:
            tag = str(tag).strip()

            if tag and tag not in normalized_tags:
                normalized_tags.append(tag)

        tags = normalized_tags

        image_queries = generate_image_queries(
            api_key,
            title,
            content_markdown,
        )

        if len(image_queries) != 5:
            raise ValueError(
                "Exactly 5 image queries are required."
            )

        slug = slugify(title)

        if not slug:
            raise ValueError("Empty slug from title.")

        errors = validate_generated_content(
            keyword,
            title,
            meta_description,
            content_markdown,
            image_queries,
            tags,
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
        print("Section-aware image queries:")

        for index, query in enumerate(
            image_queries,
            start=1,
        ):
            if index == 1:
                label = "HERO"
            else:
                label = f"H2 #{index - 1}"

            print(f"  {index}. [{label}] {query}")

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
