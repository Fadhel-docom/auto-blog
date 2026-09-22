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
FALLBACK_GROQ_MODEL = "openai/gpt-oss-20b"
MAX_RETRIES = 5
MIN_WORDS = 1500
MAX_WORDS = 2400
MIN_H2 = 10
MAX_H2 = 11
MAX_GENERATION_ATTEMPTS = 2


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
        raise ValueError("Could not find keyword column.")

    if not status_col:
        raise ValueError("Could not find status column.")

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
    (
        rows,
        fieldnames,
        keyword_col,
        status_col,
    ) = load_keywords()

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

    raise RuntimeError("No pending keyword found.")


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
            str(row.get(keyword_col, "")).strip()
            == keyword
        ):
            row[status_col] = "processing"
            found = True
            break

    if not found:
        raise ValueError(f"Keyword not found: {keyword}")

    save_keywords(rows, fieldnames)


def mark_keyword_pending(keyword):
    (
        rows,
        fieldnames,
        keyword_col,
        status_col,
    ) = load_keywords()

    for row in rows:
        if (
            str(row.get(keyword_col, "")).strip()
            == keyword
        ):
            row[status_col] = "pending"
            break

    save_keywords(rows, fieldnames)


def slugify(text):
    stop_words = {
        "for", "to", "of", "the", "a", "an",
        "in", "on", "at", "and", "or", "with",
        "how", "your", "this", "that", "from",
        "into",
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
        code = getattr(
            response,
            "status_code",
            None,
        )

        if code is not None:
            return code

    code = getattr(exc, "status_code", None)

    return code


def call_groq_with_fallback(
    api_key,
    messages,
    temperature,
    max_tokens,
    response_format,
    primary_model=GROQ_MODEL,
    fallback_model=FALLBACK_GROQ_MODEL,
):
    client = Groq(api_key=api_key)

    retryable_codes = {
        429,
        500,
        502,
        503,
        504,
    }

    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Calling Groq with model={primary_model} "
                f"(attempt {attempt}/{MAX_RETRIES})..."
            )

            response = client.chat.completions.create(
                model=primary_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

            print(
                f"Groq succeeded with model={primary_model}."
            )

            return response

        except Exception as exc:
            last_exception = exc
            status_code = get_exception_status_code(exc)

            print(
                f"Groq request failed "
                f"(model={primary_model}, "
                f"attempt={attempt}/{MAX_RETRIES}, "
                f"status={status_code}): {exc}",
                file=sys.stderr,
            )

            if status_code == 429:
                print(
                    "Primary model failed with 429."
                )
                print(
                    "Switching to fallback model: "
                    f"{fallback_model}"
                )
                break

            if (
                status_code is not None
                and status_code not in retryable_codes
            ):
                raise

            if attempt >= MAX_RETRIES:
                raise RuntimeError(
                    "Primary Groq model failed after "
                    f"{MAX_RETRIES} attempts: "
                    f"{last_exception}"
                ) from last_exception

            delay = min(
                2 ** (attempt - 1),
                30,
            )

            print(
                f"Retrying primary model in {delay}s..."
            )
            time.sleep(delay)

    fallback_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Generating with fallback "
                f"(attempt {attempt}/{MAX_RETRIES})..."
            )

            response = client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

            print(
                "Groq fallback succeeded with "
                f"model={fallback_model}."
            )

            return response

        except Exception as exc:
            fallback_exception = exc
            status_code = get_exception_status_code(exc)

            print(
                f"Groq fallback failed "
                f"(model={fallback_model}, "
                f"attempt={attempt}/{MAX_RETRIES}, "
                f"status={status_code}): {exc}",
                file=sys.stderr,
            )

            if (
                status_code is not None
                and status_code not in retryable_codes
            ):
                raise

            if attempt >= MAX_RETRIES:
                break

            delay = min(
                2 ** (attempt - 1),
                30,
            )

            print(
                f"Retrying fallback in {delay}s..."
            )
            time.sleep(delay)

    raise RuntimeError(
        "Groq fallback failed after "
        f"{MAX_RETRIES} attempts using "
        f"model '{fallback_model}': "
        f"{fallback_exception}"
    ) from fallback_exception


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
        text = re.sub(
            r"\s*```$",
            "",
            text,
        ).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise ValueError(
                "No JSON object found."
            )

        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON: {exc}"
            ) from exc


def pick_specific_angle(api_key, keyword):
    system_prompt = """
You are an expert editorial strategist for an English-language website about Home Organization & Small-Space Living.

Your job is to turn broad SEO keywords into specific, useful, practical article angles.

For the supplied keyword:
1. Generate exactly 5 distinct article angles.
2. Each angle must be substantially narrower and more specific than the original keyword.
3. Avoid generic angles such as "best ideas", "complete guide", "tips and tricks" unless narrowed to a clearly defined situation.
4. Prefer angles based on: a specific room, a specific storage problem, a specific type of small home, a specific constraint, a specific household situation, measurements, renter-friendly limitations, or a specific before/after problem.
5. The angle should be specific enough that two writers using the same keyword would be unlikely to produce the same article.
6. The angle must still be useful and fit the Home Organization & Small-Space Living niche.
7. Do not invent statistics, studies, expert quotes, or factual claims.

After generating the five angles, select the SINGLE angle that is the most specific, concrete, useful, and actionable.

Return ONLY valid JSON in exactly this structure:

{
  "angles": ["angle 1", "angle 2", "angle 3", "angle 4", "angle 5"],
  "selected_angle": "the most specific angle"
}
""".strip()

    user_prompt = f"""
Focus keyword: {keyword}

Generate exactly five narrow article angles for this keyword, then select the most specific and actionable one.

Return only the required JSON object.
""".strip()

    print("Selecting article angle with Groq...")

    response = call_groq_with_fallback(
        api_key=api_key,
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
            " <-- SELECTED"
            if angle == selected_angle
            else ""
        )
        print(f"{index}. {angle}{marker}")

    return selected_angle


def generate_with_groq(
    api_key,
    keyword,
    specific_angle,
    extra_strict=False,
):
    strict_note = ""

    if extra_strict:
        strict_note = (
            "\n\nIMPORTANT - RETRY: The previous attempt "
            "produced an article that was too short. "
            "You MUST write at least 1900 words this time. "
            "Expand every section with concrete examples, "
            "measurements, and step-by-step details. "
            "Do not summarize. Do not stop early.\n"
        )

    system_prompt = """
You are an expert long-form SEO content writer and practical home-organization editor for an English-language website about Home Organization & Small-Space Living.

Your job is to create ONE genuinely useful, original article that solves a specific reader problem.

EDITORIAL DIRECTION:
- Start from the supplied focus keyword.
- Build the entire article around the supplied specific angle.
- The specific angle is the central subject of the article.
- Do not broaden the article into a generic guide.

LENGTH (MANDATORY):
- Write EXACTLY 1900-2100 words of actual article content.
- You MUST produce at least 1900 words.
- DO NOT stop writing before 1900 words.
- If you feel you are finishing early, add more detailed sections, more examples, more measurements, more step-by-step detail.
- After writing, count the words internally. If below 1900, keep writing.
- Do NOT exceed 2400 words.

TITLE REQUIREMENT:
- The article title must be concise, specific, and easy to scan.
- Aim for 45-65 characters.
- Never exceed 70 characters unless the exact focus keyword makes this impossible.
- Preserve the exact focus keyword naturally in the title.

STRUCTURE (MANDATORY):
- Use EXACTLY 10 H2 headings.
- 11 H2 headings are allowed only if absolutely necessary.
- NEVER use fewer than 10 H2 headings.
- NEVER use more than 11 H2 headings.
- Use H3 headings when they genuinely improve organization.
- Do not use an H1 inside content_markdown.
- Use short paragraphs (2-4 sentences).
- Use numbered steps for processes.
- Use bullet lists for scanability.
- End with a practical conclusion.

HEADING FORMAT RULES:
- Use ONLY ASCII characters in H2 and H3.
- Use A-Z, a-z, 0-9, spaces, and regular hyphen (-).
- NEVER use en-dash, em-dash, or non-breaking hyphen.
- Replace "&" with "and".
- Do not use parentheses, brackets, or special punctuation in headings.
- Use "Step 1 - Title" format.

CONTENT QUALITY:
- Give concrete, practical advice.
- Include 5+ concrete examples relevant to real homes.
- Include useful measurements or dimensions in every relevant section.
- Include common mistakes, trade-offs, or considerations.
- Include approximately 3 generic product recommendations.
- Avoid vague advice. Avoid repetitive tips.

SEO:
- The exact focus keyword must appear in the title.
- The exact focus keyword MUST appear naturally within the FIRST 100 WORDS of the article.
- Do not keyword-stuff.
- The meta description MUST be between 140 and 160 characters (count carefully).

ACCURACY:
- Do not invent statistics, studies, quotes, or citations.
- Do not use placeholders.
- Do not mention AI generation.

IMAGES:
- DO NOT generate image queries or image markdown.

OUTPUT:
Return ONLY one valid JSON object:

{
  "title": "string",
  "meta_description": "string",
  "content_markdown": "string",
  "tags": ["string", "string"]
}

Do not wrap in Markdown code fences.
""".strip() + strict_note

    user_prompt = f"""
Write a complete long-form SEO article for the following focus keyword:

{keyword}

SPECIFIC ARTICLE ANGLE:
{specific_angle}

Website niche: Home Organization & Small-Space Living

MANDATORY:
- The specific angle above is the central subject.
- Do NOT write a generic article about "{keyword}".
- The article MUST be at least 1900 words.
- The article MUST contain EXACTLY 10 H2 headings (11 max).
- The exact focus keyword MUST appear in the title.
- The exact focus keyword MUST appear in the first 100 words.
- Meta description MUST be 140-160 characters.

Return only the required JSON object.
""".strip()

    response = call_groq_with_fallback(
        api_key=api_key,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=14000,
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


def generate_image_queries(
    api_key,
    title,
    content_markdown,
):
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
        body = re.sub(
            r"\n{3,}",
            "\n\n",
            body,
        ).strip()

        section_payload.append(
            f"""
SECTION {index}
H2: {section["heading"]}
SECTION CONTENT:
{body}
""".strip()
        )

    sections_text = "\n\n".join(section_payload)

    system_prompt = """
You are a professional visual content editor for an English-language Home Organization & Small-Space Living website.

Your job is to create exactly 5 highly relevant, visually distinct Pexels search queries AFTER reading a completed article.

QUERY STRUCTURE:

1. Query 1: HERO
   - Wide-shot editorial scene representing the whole article.
   - Show the whole room/space, not a close-up.
   - Realistic home environment with clear context.

2. Queries 2-5:
   - Each represents one of the four supplied H2 sections.
   - Strongly grounded in the actual section content.
   - Show concrete photographable situations.

VISUAL DIVERSITY:
- The 5 queries must be VISUALLY DIVERSE.
- Avoid 5 nearly identical "organized home" photos.

PRACTICAL RULES:
- Return exactly 5 unique queries.
- Concise English. 5-14 words.
- Concrete visual nouns (rooms, objects, storage solutions).
- No photographer names. No quotation marks.
- No camera settings. No SEO keywords.
- Prefer realistic searchable stock photo scenes.

Return ONLY valid JSON:

{
  "image_queries": [
    "wide-shot hero query",
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

{sections_text}

Generate 1 wide-shot hero + 4 section-specific queries.

Return exactly 5 unique Pexels queries in the required JSON.
""".strip()

    response = call_groq_with_fallback(
        api_key=api_key,
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


def extract_generated_fields(generated, keyword):
    title = require_string(generated, "title")
    meta_description = require_string(
        generated, "meta_description"
    )
    content_markdown = require_string(
        generated, "content_markdown"
    )

    raw_tags = generated.get("tags")

    if raw_tags is None:
        tags = [keyword]
    elif isinstance(raw_tags, list):
        tags = raw_tags
    elif isinstance(raw_tags, str):
        stripped = raw_tags.strip()
        tags = [stripped] if stripped else [keyword]
    elif isinstance(raw_tags, dict):
        tags = list(raw_tags.values())
    elif isinstance(raw_tags, (int, float, bool)):
        tags = [str(raw_tags)]
    else:
        tags = [keyword]

    normalized_tags = []

    for tag in tags:
        if not isinstance(tag, str):
            continue

        tag = tag.strip()

        if tag and tag not in normalized_tags:
            normalized_tags.append(tag)

    if not normalized_tags:
        normalized_tags = [keyword]

    return (
        title,
        meta_description,
        content_markdown,
        normalized_tags,
    )


def clean_markdown(content):
    content = str(content).strip()
    content = re.sub(
        r"^```(?:markdown|md)?\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"\s*```$",
        "",
        content,
    )
    content = re.sub(
        r"^\s*#\s+.+?\n+",
        "",
        content,
        count=1,
    )
    content = re.sub(
        r"(?mi)^[ \t]*Tags:[ \t]*\[[^\r\n]*\][ \t]*\r?\n?",
        "",
        content,
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


def count_h2(content: str) -> int:
    return len(
        re.findall(
            r"^\s*##\s+\S+",
            content,
            re.MULTILINE,
        )
    )


def generate_article_with_retry(
    api_key,
    keyword,
    specific_angle,
):
    last_result = None

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        extra_strict = attempt > 1

        print("")
        print(
            f"=== Generation attempt "
            f"{attempt}/{MAX_GENERATION_ATTEMPTS} "
            f"(strict={extra_strict}) ==="
        )

        generated = generate_with_groq(
            api_key,
            keyword,
            specific_angle,
            extra_strict=extra_strict,
        )

        (
            title,
            meta_description,
            content_markdown,
            tags,
        ) = extract_generated_fields(generated, keyword)

        title = title.strip()
        meta_description = meta_description.strip()
        content_markdown = clean_markdown(content_markdown)

        words = count_words(content_markdown)
        h2_count = count_h2(content_markdown)

        print(
            f"Attempt {attempt} produced: "
            f"{words} words, {h2_count} H2"
        )

        last_result = (
            title,
            meta_description,
            content_markdown,
            tags,
            words,
            h2_count,
        )

        if (
            words >= MIN_WORDS
            and MIN_H2 <= h2_count <= MAX_H2
        ):
            print(
                f"Attempt {attempt} accepted: "
                f"{words} words, {h2_count} H2"
            )
            return last_result

        print(
            f"Attempt {attempt} rejected: "
            f"needs >= {MIN_WORDS} words and "
            f"{MIN_H2}-{MAX_H2} H2"
        )

        if attempt < MAX_GENERATION_ATTEMPTS:
            delay = 3
            print(
                f"Retrying generation in "
                f"{delay}s..."
            )
            time.sleep(delay)

    if last_result is None:
        raise RuntimeError(
            "No generation attempt produced output."
        )

    print(
        "WARNING: using last attempt despite "
        "not meeting thresholds."
    )
    return last_result


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
            f"Selected specific angle: "
            f"{specific_angle}"
        )

        (
            title,
            meta_description,
            content_markdown,
            tags,
            word_count,
            h2_count,
        ) = generate_article_with_retry(
            api_key,
            keyword,
            specific_angle,
        )

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
            "h2_count": h2_count,
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
        print(f"H2 count: {h2_count}")

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
