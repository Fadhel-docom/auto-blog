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
MIN_ACCEPTABLE_WORDS = 1300
MAX_WORDS = 2400

MIN_H2 = 10
MAX_H2 = 11

MAX_GENERATION_ATTEMPTS = 2

MAX_TITLE_LENGTH = 70
MAX_META_LENGTH = 158
MIN_META_LENGTH = 130

MAX_OUTPUT_TOKENS = 10000
SHORT_ARTICLE_RETRY_TOKENS = 6000

VERY_SHORT_WORDS = 500
SHORT_WORDS_UPPER_BOUND = 1500
FALLBACK_MIN_WORDS_CHECK = 1400

ARTICLE_TEMPERATURE = 0.5


class TruncatedJSONError(ValueError):
    pass


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
        "r", encoding="utf-8-sig", newline="",
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
        fieldnames, ["status", "state"],
    )

    if not keyword_col:
        raise ValueError("Could not find keyword column.")

    if not status_col:
        raise ValueError("Could not find status column.")

    return (rows, fieldnames, keyword_col, status_col)


def save_keywords(rows, fieldnames):
    temp_path = KEYWORDS_PATH.with_suffix(".csv.tmp")

    with temp_path.open(
        "w", encoding="utf-8", newline="",
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    temp_path.replace(KEYWORDS_PATH)


def get_first_pending_keyword():
    (rows, fieldnames, keyword_col, status_col) = load_keywords()

    for row in rows:
        keyword = str(row.get(keyword_col, "")).strip()
        status = str(row.get(status_col, "")).strip().lower()

        if keyword and status == "pending":
            return (keyword, rows, fieldnames, keyword_col, status_col)

    raise RuntimeError("No pending keyword found.")


def mark_keyword_processing(keyword, rows, fieldnames, keyword_col, status_col):
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
    (rows, fieldnames, keyword_col, status_col) = load_keywords()

    for row in rows:
        if str(row.get(keyword_col, "")).strip() == keyword:
            row[status_col] = "pending"
            break

    save_keywords(rows, fieldnames)


def slugify(text):
    stop_words = {
        "for", "to", "of", "the", "a", "an", "in", "on",
        "at", "and", "or", "with", "how", "your", "this",
        "that", "from", "into",
    }

    text = str(text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text).strip("-")

    if not text:
        return ""

    raw_words = text.split("-")
    useful_words = [
        word for word in raw_words
        if word and word not in stop_words
    ]

    if not useful_words:
        useful_words = raw_words[:6]

    selected_words = useful_words[:3]

    for index, word in enumerate(useful_words):
        if re.search(r"\d", word):
            for candidate_word in useful_words[index:index + 4]:
                if candidate_word not in selected_words:
                    selected_words.append(candidate_word)
            break

    for word in useful_words:
        if word in selected_words:
            continue

        candidate = "-".join(selected_words + [word])
        if len(candidate) > 50:
            break

        selected_words.append(word)

        if len(selected_words) >= 7:
            break

    slug = "-".join(selected_words).strip("-")

    if len(slug) > 50:
        slug = slug[:50].rstrip("-")

    if not slug:
        slug = "-".join(text.split("-")[:6]).strip("-")

    return slug


def get_exception_status_code(exc):
    response = getattr(exc, "response", None)

    if response is not None:
        code = getattr(response, "status_code", None)
        if code is not None:
            return code

    return getattr(exc, "status_code", None)


def get_finish_reason(response):
    try:
        if not response.choices:
            return None
        return getattr(response.choices[0], "finish_reason", None)
    except Exception:
        return None


def get_response_content(response):
    if not response.choices:
        raise ValueError("No choices returned.")

    content = getattr(response.choices[0].message, "content", None)

    if not content:
        raise ValueError("Empty message content.")

    if not isinstance(content, str):
        raise ValueError("Response content is not a string.")

    return content


def get_response_model(response, requested_model=None):
    model = getattr(response, "model", None)
    if model:
        return str(model)
    return requested_model or "unknown"


def log_response_metadata(response, requested_model=None, label="Groq response"):
    actual_model = get_response_model(response, requested_model)
    finish_reason = get_finish_reason(response)
    usage = getattr(response, "usage", None)
    completion_tokens = None

    if usage is not None:
        completion_tokens = getattr(usage, "completion_tokens", None)

    print(
        f"{label}: "
        f"model={actual_model}, "
        f"finish_reason={finish_reason}, "
        f"completion_tokens={completion_tokens}"
    )


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
    retryable_codes = {429, 500, 502, 503, 504}
    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Calling Groq with model={primary_model} "
                f"(attempt {attempt}/{MAX_RETRIES}, "
                f"max_tokens={max_tokens}, "
                f"temperature={temperature})..."
            )

            response = client.chat.completions.create(
                model=primary_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

            log_response_metadata(response, requested_model=primary_model)
            print(f"Groq succeeded with model={primary_model}.")

            return (response, get_response_model(response, primary_model))

        except Exception as exc:
            last_exception = exc
            status_code = get_exception_status_code(exc)

            print(
                "Groq request failed "
                f"(model={primary_model}, "
                f"attempt={attempt}/{MAX_RETRIES}, "
                f"status={status_code}): {exc}",
                file=sys.stderr,
            )

            if status_code == 429:
                print("Primary model failed with 429.")
                print(
                    "Switching immediately to "
                    f"fallback model: {fallback_model}"
                )
                break

            if (status_code is not None
                    and status_code not in retryable_codes):
                raise

            if attempt >= MAX_RETRIES:
                raise RuntimeError(
                    f"Primary Groq model failed after "
                    f"{MAX_RETRIES} attempts: {last_exception}"
                ) from last_exception

            delay = min(2 ** (attempt - 1), 30)
            print(f"Retrying primary model in {delay}s...")
            time.sleep(delay)

    fallback_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Generating with fallback "
                f"model={fallback_model} "
                f"(attempt {attempt}/{MAX_RETRIES}, "
                f"max_tokens={max_tokens}, "
                f"temperature={temperature})..."
            )

            response = client.chat.completions.create(
                model=fallback_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )

            log_response_metadata(response, requested_model=fallback_model)
            print(f"Groq fallback succeeded with model={fallback_model}.")

            return (response, get_response_model(response, fallback_model))

        except Exception as exc:
            fallback_exception = exc
            status_code = get_exception_status_code(exc)

            print(
                "Groq fallback failed "
                f"(model={fallback_model}, "
                f"attempt={attempt}/{MAX_RETRIES}, "
                f"status={status_code}): {exc}",
                file=sys.stderr,
            )

            if (status_code is not None
                    and status_code not in retryable_codes):
                raise

            if attempt >= MAX_RETRIES:
                break

            delay = min(2 ** (attempt - 1), 30)
            print(f"Retrying fallback in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(
        f"Groq fallback failed after {MAX_RETRIES} "
        f"attempts using model '{fallback_model}': "
        f"{fallback_exception}"
    ) from fallback_exception


def strip_code_fences(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(
            r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE,
        )
        text = re.sub(r"\s*```$", "", text).strip()

    return text


def extract_balanced_json_object(text):
    if not isinstance(text, str):
        raise ValueError("Response is not a string.")

    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object start found.")

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            depth += 1
            continue

        if char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    raise TruncatedJSONError(
        "JSON object appears truncated: no balanced closing brace found."
    )


def extract_json_from_response(response_text, finish_reason=None):
    if not isinstance(response_text, str):
        raise ValueError("Response is not a string.")

    text = response_text.strip()
    if not text:
        raise ValueError("Empty response.")

    text = strip_code_fences(text)

    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError("JSON response is not an object.")
        return result
    except json.JSONDecodeError:
        pass

    try:
        balanced = extract_balanced_json_object(text)
        result = json.loads(balanced)

        if not isinstance(result, dict):
            raise ValueError("Recovered JSON is not an object.")

        print(
            "JSON recovery succeeded: "
            "a valid balanced JSON object was found."
        )
        return result

    except TruncatedJSONError as exc:
        if finish_reason == "length":
            raise TruncatedJSONError(
                "Groq reported finish_reason=length and "
                "the JSON object is incomplete."
            ) from exc
        raise

    except json.JSONDecodeError as exc:
        if finish_reason == "length":
            raise TruncatedJSONError(
                "Groq reported finish_reason=length and "
                "the JSON could not be parsed."
            ) from exc
        raise ValueError(f"Invalid JSON: {exc}") from exc


def validate_article_json_structure(generated):
    if not isinstance(generated, dict):
        raise ValueError("Generated article is not a JSON object.")

    required_fields = ("title", "meta_description", "content_markdown")
    missing = [f for f in required_fields if f not in generated]

    if missing:
        raise ValueError(
            "Generated JSON is missing required fields: "
            + ", ".join(missing)
        )

    return True


def pick_specific_angle(api_key, keyword):
    system_prompt = """
You are an editorial strategist for a Home Organization website.

Generate exactly 5 narrow article angles. Then select the most specific.

Prefer:
- a specific room
- a specific storage problem
- a specific constraint
- measurements
- renter limitations
- a concrete before/after situation

Return ONLY valid JSON.

Return the JSON object in ONE line.
Do not put unnecessary newlines inside JSON strings.

{
  "angles": ["a1", "a2", "a3", "a4", "a5"],
  "selected_angle": "the most specific"
}
""".strip()

    user_prompt = f"""
Keyword: {keyword}

Generate exactly five narrow angles and select the most specific,
concrete, useful, actionable one.

Return only the JSON object in ONE line.
""".strip()

    print("Selecting article angle with Groq...")

    response, actual_model = call_groq_with_fallback(
        api_key=api_key,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.6,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    content = get_response_content(response)
    finish_reason = get_finish_reason(response)

    result = extract_json_from_response(content, finish_reason=finish_reason)

    if not isinstance(result, dict):
        raise ValueError("Angle response is not a JSON object.")

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
        raise ValueError("Groq must return exactly 5 unique angles.")

    selected_angle = result.get("selected_angle")
    if not isinstance(selected_angle, str):
        raise ValueError("'selected_angle' must be a string.")

    selected_angle = selected_angle.strip()
    if not selected_angle:
        raise ValueError("'selected_angle' is empty.")

    if selected_angle not in angles:
        selected_angle = angles[0]

    print(f"Angle model: {actual_model}")
    print("Generated 5 article angles:")

    for index, angle in enumerate(angles, start=1):
        marker = " <-- SELECTED" if angle == selected_angle else ""
        print(f"{index}. {angle}{marker}")

    return selected_angle


def build_article_messages(
    keyword, specific_angle,
    attempt_number=1, short_retry=False,
):
    retry_note = ""

    if attempt_number >= 2:
        retry_note += """
CRITICAL RETRY:
The previous article did not satisfy the minimum requirements.

This attempt MUST produce a genuinely complete article.
Do not stop early.
Do not summarize.
Do not compress sections.

Write all 10 H2 sections completely.
Each H2 section should contain substantial practical detail.
""".strip()

    if short_retry:
        retry_note += """

CRITICAL LENGTH RECOVERY:
The previous GPT-OSS 120B response was too short.

Produce the COMPLETE article this time.
The article must contain at least 1500 actual article words.
Use 10 H2 sections.
Aim for approximately 1600-1800 words.
Do not stop after the introduction.
Do not return a partial article.
""".strip()

    system_prompt = f"""
You are an expert home-organization writer.

Write ONE complete, practical, original article for an
English-language Home Organization and Small-Space Living website.

The supplied specific angle is mandatory.

WORD COUNT:
- Target: 1600-1800 actual article words.
- Minimum: 1500 actual article words.
- Maximum: 2400 actual article words.
- Write EXACTLY 10 H2 sections.
- Aim for roughly 150-190 words per H2 section.
- Every section must contain useful practical information.
- Do not intentionally write a short article.
- Do not summarize the article.
- Do not stop early.

STRUCTURE:
- Exactly 10 H2 headings starting with "## ".
- Short paragraphs, normally 2-4 sentences.
- Use numbered steps where useful.
- Use bullet lists where they improve readability.
- End with a practical conclusion and natural CTA.

HEADING RULES:
- ASCII only.
- Use A-Z, a-z, 0-9, spaces, and regular hyphen.
- Never use em-dash.
- Never use en-dash.
- Never use non-breaking hyphen.
- Replace "&" with "and".
- No parentheses in headings.
- No brackets in headings.
- Keep headings concise.
- "Step 1 - Title" is allowed.

CONTENT:
- Give concrete, practical advice.
- Include realistic measurements or dimensions where useful.
- Include real-home examples.
- Include common mistakes and trade-offs.
- Include approximately 3 generic product recommendations.
- Never invent brands, prices, reviews, statistics, studies, expert quotes, or citations.
- Do not use placeholders.
- Do not mention AI generation.
- Do not generate image queries.
- Do not include image markdown.

SEO:
- Exact focus keyword must appear naturally in title.
- Exact focus keyword must appear naturally in the introduction.
- Do not keyword stuff.
- Meta description should be approximately 140-158 characters.

TITLE:
- 45-68 characters when possible.
- Must contain the exact focus keyword.
- Clear and specific.
- Avoid generic list-style phrasing.

OUTPUT:
Return ONLY one valid JSON object.

Required shape:

{{
  "title": "string",
  "meta_description": "string",
  "content_markdown": "string",
  "tags": ["tag1", "tag2", "tag3"]
}}

IMPORTANT JSON RULE:
Return the complete JSON object in ONE LINE.
Do NOT insert unnecessary newlines inside JSON string values.
Escape JSON quotation marks correctly.
Do not wrap the JSON in Markdown code fences.

{retry_note}
""".strip()

    user_prompt = f"""
Focus keyword:
{keyword}

SPECIFIC ARTICLE ANGLE:
{specific_angle}

Write the complete article now.

Hard requirements:
- 1500+ actual article words.
- 10 H2 sections.
- 1600-1800 words is the preferred target.
- Exact keyword in title.
- Exact keyword naturally in introduction.
- Complete JSON object.
- JSON in ONE line.
- No image queries.
- No Markdown code fence.
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def parse_article_response(response, actual_model):
    content = get_response_content(response)
    finish_reason = get_finish_reason(response)

    print(
        f"Article response metadata: "
        f"model={actual_model}, finish_reason={finish_reason}"
    )

    if finish_reason == "length":
        print("WARNING: finish_reason=length. Model may be truncated.")

    generated = extract_json_from_response(
        content, finish_reason=finish_reason,
    )

    validate_article_json_structure(generated)

    return (generated, content, finish_reason)


def call_article_generation(api_key, keyword, specific_angle, attempt_number=1):
    messages = build_article_messages(
        keyword=keyword,
        specific_angle=specific_angle,
        attempt_number=attempt_number,
        short_retry=False,
    )

    response, actual_model = call_groq_with_fallback(
        api_key=api_key,
        messages=messages,
        temperature=ARTICLE_TEMPERATURE,
        max_tokens=MAX_OUTPUT_TOKENS,
        response_format={"type": "json_object"},
    )

    try:
        (generated, raw_content, finish_reason) = parse_article_response(
            response, actual_model,
        )
    except TruncatedJSONError as exc:
        print("Article JSON is truncated.")
        print(f"Reason: {exc}")

        if actual_model == GROQ_MODEL:
            retry_messages = build_article_messages(
                keyword=keyword,
                specific_angle=specific_angle,
                attempt_number=attempt_number + 1,
                short_retry=True,
            )

            print("Retrying GPT-OSS 120B because JSON was truncated...")

            response, actual_model = call_groq_with_fallback(
                api_key=api_key,
                messages=retry_messages,
                temperature=ARTICLE_TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
            )

            (generated, raw_content, finish_reason) = parse_article_response(
                response, actual_model,
            )
        else:
            raise

    (_title, _meta, content_markdown, _tags) = extract_generated_fields(
        generated, keyword,
    )
    content_markdown = clean_markdown(content_markdown)
    words = count_words(content_markdown)

    print(
        f"Smart Groq article result: "
        f"model={actual_model}, "
        f"finish_reason={finish_reason}, "
        f"words={words}"
    )

    if actual_model == GROQ_MODEL:
        if words < VERY_SHORT_WORDS:
            print(f"GPT-OSS 120B produced only {words} words.")
            print("This is below the 500-word threshold.")

            retry_messages = build_article_messages(
                keyword=keyword,
                specific_angle=specific_angle,
                attempt_number=attempt_number + 1,
                short_retry=True,
            )

            print(f"Retrying GPT-OSS 120B with max_tokens={MAX_OUTPUT_TOKENS}...")

            response, retry_model = call_groq_with_fallback(
                api_key=api_key,
                messages=retry_messages,
                temperature=ARTICLE_TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
            )

            (generated, raw_content, finish_reason) = parse_article_response(
                response, retry_model,
            )
            return generated, retry_model, finish_reason

        if VERY_SHORT_WORDS <= words < SHORT_WORDS_UPPER_BOUND:
            print(f"GPT-OSS 120B produced {words} words.")
            print("This is in the 500-1499 range.")

            retry_messages = build_article_messages(
                keyword=keyword,
                specific_angle=specific_angle,
                attempt_number=attempt_number + 1,
                short_retry=True,
            )

            print(f"Retrying GPT-OSS 120B with max_tokens={SHORT_ARTICLE_RETRY_TOKENS}...")

            response, retry_model = call_groq_with_fallback(
                api_key=api_key,
                messages=retry_messages,
                temperature=ARTICLE_TEMPERATURE,
                max_tokens=SHORT_ARTICLE_RETRY_TOKENS,
                response_format={"type": "json_object"},
            )

            (generated, raw_content, finish_reason) = parse_article_response(
                response, retry_model,
            )
            return generated, retry_model, finish_reason

        if finish_reason == "length":
            print("GPT-OSS 120B returned finish_reason=length.")

            retry_messages = build_article_messages(
                keyword=keyword,
                specific_angle=specific_angle,
                attempt_number=attempt_number + 1,
                short_retry=True,
            )

            print("Retrying because finish_reason=length...")

            response, retry_model = call_groq_with_fallback(
                api_key=api_key,
                messages=retry_messages,
                temperature=ARTICLE_TEMPERATURE,
                max_tokens=MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
            )

            (generated, raw_content, finish_reason) = parse_article_response(
                response, retry_model,
            )
            return generated, retry_model, finish_reason

    if actual_model == FALLBACK_GROQ_MODEL:
        if words < FALLBACK_MIN_WORDS_CHECK:
            print(f"WARNING: fallback 20B produced only {words} words.")
            print("Performing manual JSON/truncation validation...")

            if finish_reason == "length":
                raise TruncatedJSONError(
                    f"Fallback GPT-OSS 20B returned finish_reason=length "
                    f"and produced only {words} words."
                )

            print("Fallback JSON is structurally valid.")
            print(
                f"Article is below {MIN_WORDS}-word target. "
                "Normal generation retry will attempt again."
            )

    return (generated, actual_model, finish_reason)


def generate_with_groq(api_key, keyword, specific_angle, attempt_number=1):
    generated, actual_model, finish_reason = call_article_generation(
        api_key=api_key,
        keyword=keyword,
        specific_angle=specific_angle,
        attempt_number=attempt_number,
    )

    validate_article_json_structure(generated)

    print(
        f"Article generation completed: "
        f"model={actual_model}, "
        f"finish_reason={finish_reason}"
    )

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

        if stripped.startswith("```") or stripped.startswith("~~~"):
            if not in_fenced_code_block:
                in_fenced_code_block = True
                fence_marker = "```" if stripped.startswith("```") else "~~~"
            elif fence_marker and stripped.startswith(fence_marker):
                in_fenced_code_block = False
                fence_marker = None

            if current_heading is not None:
                current_body.append(line)
            continue

        if not in_fenced_code_block:
            match = re.match(r"^\s*##[ \t]+([^#].*?)\s*$", line)

            if match:
                if current_heading is not None:
                    sections.append({
                        "heading": current_heading,
                        "body": "\n".join(current_body).strip(),
                    })

                current_heading = match.group(1).strip()
                current_body = []
                continue

        if current_heading is not None:
            current_body.append(line)

    if current_heading is not None:
        sections.append({
            "heading": current_heading,
            "body": "\n".join(current_body).strip(),
        })

    return sections


def generate_image_queries(api_key, title, content_markdown):
    sections = extract_h2_sections(content_markdown)

    if len(sections) < 4:
        raise ValueError("At least 4 H2 sections are required.")

    selected_sections = sections[:4]
    section_payload = []

    for index, section in enumerate(selected_sections, start=1):
        body = re.sub(r"\n{3,}", "\n\n", section["body"]).strip()[:500]
        section_payload.append(
            f"SECTION {index}\n"
            f"H2: {section['heading']}\n"
            f"CONTENT: {body}\n"
        )

    sections_text = "\n".join(section_payload)

    system_prompt = """
You are a visual content editor for a Home Organization website.

Create exactly 5 highly relevant and visually distinct Pexels search queries.

Query 1: HERO - wide editorial shot of whole room.
Queries 2-5: one per H2 section.

RULES:
- Exactly 5 unique queries.
- 5-14 words per query.
- Concrete visual nouns.
- No photographer names.
- No generic SEO keyword stuffing.

Return ONLY valid JSON.

Return JSON in ONE line.

{
  "image_queries": ["q1", "q2", "q3", "q4", "q5"]
}
""".strip()

    user_prompt = (
        f"TITLE: {title}\n\n"
        f"{sections_text}\n\n"
        "Return JSON with exactly 5 unique queries in ONE line."
    )

    response, actual_model = call_groq_with_fallback(
        api_key=api_key,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )

    content = get_response_content(response)
    finish_reason = get_finish_reason(response)

    result = extract_json_from_response(content, finish_reason=finish_reason)

    if not isinstance(result, dict):
        raise ValueError("Image-query response is not a JSON object.")

    raw_queries = result.get("image_queries")
    if not isinstance(raw_queries, list):
        raise ValueError("'image_queries' must be a list.")

    image_queries = []
    for query in raw_queries:
        if not isinstance(query, str):
            continue
        query = query.strip()
        if query and query not in image_queries:
            image_queries.append(query)

    if len(image_queries) != 5:
        raise ValueError("Groq must return exactly 5 unique image queries.")

    print(f"Image-query model: {actual_model}")
    print("Generated 5 section-aware image queries:")

    for index, query in enumerate(image_queries, start=1):
        label = "HERO" if index == 1 else f"H2 #{index - 1}"
        print(f"  {index}. [{label}] {query}")

    return image_queries


def require_string(data, field_name):
    value = data.get(field_name)

    if not isinstance(value, str):
        raise ValueError(f"'{field_name}' must be a string.")

    value = value.strip()
    if not value:
        raise ValueError(f"'{field_name}' is empty.")

    return value


def extract_generated_fields(generated, keyword):
    validate_article_json_structure(generated)

    title = require_string(generated, "title")
    meta_description = require_string(generated, "meta_description")
    content_markdown = require_string(generated, "content_markdown")

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

    return (title, meta_description, content_markdown, normalized_tags)


def clean_markdown(content):
    content = str(content).strip()
    content = re.sub(
        r"^```(?:markdown|md)?\s*", "", content, flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)
    content = re.sub(r"^\s*#\s+.+?\n+", "", content, count=1)
    content = re.sub(
        r"(?mi)^[ \t]*Tags:[ \t]*\[[^\r\n]*\][ \t]*\r?\n?",
        "", content,
    )
    return content.strip()


def shorten_title(title, keyword):
    title = title.strip()

    if len(title) <= MAX_TITLE_LENGTH:
        return title

    trimmed = title[:MAX_TITLE_LENGTH].rstrip()
    trimmed = re.sub(r"[\s:;\-,]+$", "", trimmed)

    if keyword and keyword.lower() not in trimmed.lower():
        kw = keyword.strip()
        if len(kw) + 20 <= MAX_TITLE_LENGTH:
            trimmed = kw.title() + " - Small Space Guide"

    return trimmed


def shorten_meta(meta):
    meta = meta.strip()

    if len(meta) <= MAX_META_LENGTH:
        return meta

    trimmed = meta[:MAX_META_LENGTH].rstrip()
    last_period = trimmed.rfind(". ")

    if last_period > MIN_META_LENGTH:
        return trimmed[:last_period + 1].strip()

    last_space = trimmed.rfind(" ")

    if last_space > MIN_META_LENGTH:
        trimmed = trimmed[:last_space]

    trimmed = re.sub(r"[\s,;:\-]+$", "", trimmed)

    if not trimmed.endswith((".", "!", "?")):
        trimmed += "."

    return trimmed


def count_words(text):
    plain = re.sub(r"[!\[\]()]+", " ", text)
    plain = re.sub(r"`[^`]+`", "", plain)
    return len(re.findall(r"\b[\w'-]+\b", plain, flags=re.UNICODE))


def count_h2(content):
    return len(re.findall(r"^\s*##\s+\S+", content, re.MULTILINE))


def generate_article_with_retry(api_key, keyword, specific_angle):
    last_result = None

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        print("")
        print(f"=== Generation attempt {attempt}/{MAX_GENERATION_ATTEMPTS} ===")

        try:
            generated = generate_with_groq(
                api_key, keyword, specific_angle,
                attempt_number=attempt,
            )
        except Exception as exc:
            print(f"Attempt {attempt} error: {exc}", file=sys.stderr)

            if attempt < MAX_GENERATION_ATTEMPTS:
                print("Waiting 3 seconds before next article attempt...")
                time.sleep(3)
            continue

        try:
            (title, meta_description, content_markdown, tags) = (
                extract_generated_fields(generated, keyword)
            )
        except Exception as exc:
            print(f"Generated JSON validation failed: {exc}", file=sys.stderr)
            if attempt < MAX_GENERATION_ATTEMPTS:
                time.sleep(3)
            continue

        title = title.strip()
        meta_description = meta_description.strip()
        content_markdown = clean_markdown(content_markdown)

        original_title_length = len(title)
        original_meta_length = len(meta_description)

        title = shorten_title(title, keyword)
        meta_description = shorten_meta(meta_description)

        words = count_words(content_markdown)
        h2_count = count_h2(content_markdown)

        print(f"Attempt {attempt}: {words} words, {h2_count} H2")
        print(f"  Title: {original_title_length} -> {len(title)} chars")
        print(f"  Meta: {original_meta_length} -> {len(meta_description)} chars")

        last_result = (title, meta_description, content_markdown, tags, words, h2_count)

        if words >= MIN_WORDS and MIN_H2 <= h2_count <= MAX_H2:
            print(f"Attempt {attempt} accepted.")
            return last_result

        print(
            f"Attempt {attempt} rejected: "
            f"needs {MIN_WORDS}+ words and {MIN_H2}-{MAX_H2} H2."
        )

        if MIN_ACCEPTABLE_WORDS <= words < MIN_WORDS:
            print(
                f"Article is above the acceptable floor "
                f"({MIN_ACCEPTABLE_WORDS}) but below target."
            )

        if words < MIN_ACCEPTABLE_WORDS:
            print(f"Article is below the acceptable floor ({MIN_ACCEPTABLE_WORDS}).")

        if attempt < MAX_GENERATION_ATTEMPTS:
            print("Retrying complete article generation...")
            time.sleep(3)

    if last_result is None:
        raise RuntimeError("All article generation attempts failed.")

    (title, meta_description, content_markdown, tags, words, h2_count) = last_result

    if words < MIN_ACCEPTABLE_WORDS:
        raise RuntimeError(
            f"All generation attempts produced articles below "
            f"the acceptable minimum of {MIN_ACCEPTABLE_WORDS} words. "
            f"Last result had {words} words."
        )

    print(
        "WARNING: using last structurally acceptable attempt "
        f"even though it did not reach the preferred "
        f"{MIN_WORDS}-word target."
    )

    return last_result


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
        (keyword, rows, fieldnames, keyword_col, status_col) = (
            get_first_pending_keyword()
        )
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
        specific_angle = pick_specific_angle(api_key, keyword)
        print(f"Selected specific angle: {specific_angle}")

        (title, meta_description, content_markdown, tags,
         word_count, h2_count) = generate_article_with_retry(
            api_key, keyword, specific_angle,
        )

        image_queries = generate_image_queries(
            api_key, title, content_markdown,
        )

        if len(image_queries) != 5:
            raise ValueError("Exactly 5 image queries are required.")

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
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        save_article(article)

        print("")
        print("Article generated successfully.")
        print(f"Keyword: {keyword}")
        print(f"Title: {title}")
        print(f"Slug: {slug}")
        print(f"Word count: {word_count}")
        print(f"H2 count: {h2_count}")
        print(f"Title length: {len(title)}")
        print(f"Meta length: {len(meta_description)}")

        print("Section-aware image queries:")
        for index, query in enumerate(image_queries, start=1):
            label = "HERO" if index == 1 else f"H2 #{index - 1}"
            print(f"  {index}. [{label}] {query}")

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
