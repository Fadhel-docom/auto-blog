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
ARTICLE_TEMPERATURE = 0.5

OUTLINE_MAX_TOKENS = 800
SECTION_MAX_TOKENS = 700
IMAGE_QUERY_MAX_TOKENS = 1200

MIN_WORDS = 1500
MIN_ACCEPTABLE_WORDS = 1300
MAX_WORDS = 2400
MIN_H2 = 10
MAX_H2 = 10
REQUIRED_SECTION_COUNT = 10
MAX_SECTION_RETRIES = 1
MAX_FAILED_SECTIONS_BEFORE_PIPELINE_RESTART = 2
MAX_PIPELINE_ATTEMPTS = 2
MAX_TITLE_LENGTH = 68
MIN_META_LENGTH = 140
MAX_META_LENGTH = 158


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
            "Could not find keyword column in keywords.csv."
        )

    if not status_col:
        raise ValueError(
            "Could not find status column in keywords.csv."
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
        status = str(row.get(status_col, "")).strip().lower()

        if keyword and status == "pending":
            return (keyword, rows, fieldnames, keyword_col, status_col)

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
        raise ValueError("No choices returned by Groq.")

    content = getattr(response.choices[0].message, "content", None)

    if not content:
        raise ValueError("Groq returned empty message content.")

    if not isinstance(content, str):
        raise ValueError("Groq response content is not a string.")

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
    response_format=None,
    primary_model=GROQ_MODEL,
    fallback_model=FALLBACK_GROQ_MODEL,
):
    client = Groq(api_key=api_key)
    retryable_codes = {429, 500, 502, 503, 504}
    primary_failed_with_429 = False
    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Groq primary: {primary_model} "
                f"(attempt {attempt}/{MAX_RETRIES}, "
                f"max_tokens={max_tokens})"
            )

            kwargs = {
                "model": primary_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if response_format is not None:
                kwargs["response_format"] = response_format

            response = client.chat.completions.create(**kwargs)

            log_response_metadata(response, requested_model=primary_model)

            return (response, get_response_model(response, primary_model))

        except Exception as exc:
            last_exception = exc
            status_code = get_exception_status_code(exc)

            print(
                "Primary Groq request failed: "
                f"status={status_code}, error={exc}",
                file=sys.stderr,
            )

            if status_code == 429:
                primary_failed_with_429 = True
                print(
                    "Primary model returned 429. "
                    "Switching to fallback model."
                )
                break

            if (status_code is not None
                    and status_code not in retryable_codes):
                raise

            if attempt >= MAX_RETRIES:
                print(
                    "Primary model exhausted retries. "
                    "Switching to fallback."
                )
                break

            delay = min(2 ** (attempt - 1), 30)
            print(f"Retrying primary model in {delay}s...")
            time.sleep(delay)

    fallback_exception = None

    if primary_failed_with_429:
        print(
            "Using fallback immediately because "
            "primary returned 429."
        )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                f"Groq fallback: {fallback_model} "
                f"(attempt {attempt}/{MAX_RETRIES}, "
                f"max_tokens={max_tokens})"
            )

            kwargs = {
                "model": fallback_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            if response_format is not None:
                kwargs["response_format"] = response_format

            response = client.chat.completions.create(**kwargs)

            log_response_metadata(response, requested_model=fallback_model)

            return (response, get_response_model(response, fallback_model))

        except Exception as exc:
            fallback_exception = exc
            status_code = get_exception_status_code(exc)

            print(
                "Fallback Groq request failed: "
                f"status={status_code}, error={exc}",
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
        "Both Groq models failed. "
        f"Primary error: {last_exception}; "
        f"Fallback error: {fallback_exception}"
    )


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
        raise ValueError("No JSON object found.")

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
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    raise TruncatedJSONError("JSON object is incomplete.")


def extract_json_from_response(response_text, finish_reason=None):
    text = strip_code_fences(response_text)

    if not text:
        raise ValueError("Empty model response.")

    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError("JSON response must be an object.")
        return result
    except json.JSONDecodeError:
        pass

    try:
        balanced = extract_balanced_json_object(text)
        result = json.loads(balanced)

        if not isinstance(result, dict):
            raise ValueError("Recovered JSON must be an object.")

        return result

    except TruncatedJSONError as exc:
        if finish_reason == "length":
            raise TruncatedJSONError(
                "Groq returned finish_reason=length and JSON is truncated."
            ) from exc
        raise


def pick_specific_angle(api_key, keyword):
    system_prompt = """
You are an editorial strategist for a Home Organization website.

Generate exactly 5 narrow article angles for the keyword, then select the most specific and useful one.

Prefer:
- a specific room
- a specific storage problem
- a specific constraint
- measurements
- renter limitations
- a concrete before/after situation

Return ONLY valid JSON. Return the JSON in ONE line.

{
  "angles": ["angle 1", "angle 2", "angle 3", "angle 4", "angle 5"],
  "selected_angle": "selected angle"
}
""".strip()

    user_prompt = f"""
Focus keyword: {keyword}

Return exactly 5 unique narrow angles and select the most specific one.
""".strip()

    response, actual_model = call_groq_with_fallback(
        api_key=api_key,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.5,
        max_tokens=800,
        response_format={"type": "json_object"},
    )

    content = get_response_content(response)
    finish_reason = get_finish_reason(response)

    result = extract_json_from_response(content, finish_reason=finish_reason)

    angles = result.get("angles")
    selected_angle = result.get("selected_angle")

    if not isinstance(angles, list):
        raise ValueError("Angle response must contain an angles list.")

    angles = [str(a).strip() for a in angles if str(a).strip()]

    if len(angles) != 5:
        raise ValueError("Angle generator must return exactly 5 angles.")

    if not isinstance(selected_angle, str):
        raise ValueError("selected_angle must be a string.")

    selected_angle = selected_angle.strip()

    if selected_angle not in angles:
        selected_angle = angles[0]

    print(f"Angle model: {actual_model}")
    print(f"Selected angle: {selected_angle}")

    return selected_angle


def clean_heading(heading):
    heading = str(heading).strip()
    heading = re.sub(r"^\s*#+\s*", "", heading)
    heading = heading.replace("—", "-")
    heading = heading.replace("–", "-")
    heading = heading.replace("&", "and")
    heading = re.sub(r"\s+", " ", heading).strip()
    heading = heading.strip(" \t#")

    return heading


def generate_outline(api_key, keyword, specific_angle):
    system_prompt = """
You are an expert editorial planner for a Home Organization website.

Create the complete outline for ONE practical article.

The article must be specific, useful, realistic, and focused on the supplied keyword and article angle.

Return ONLY this JSON object:

{
  "title": "...",
  "meta_description": "...",
  "tags": ["...", "...", "..."],
  "h2_headings": [
    "...", "...", "...", "...", "...",
    "...", "...", "...", "...", "..."
  ]
}

HARD RULES:

TITLE:
- Must contain the exact focus keyword.
- Maximum 68 characters.
- Clear and specific.
- No clickbait.

META DESCRIPTION:
- 140-158 characters.
- Natural English.
- Useful and descriptive.
- No keyword stuffing.

TAGS:
- Exactly 3 tags.
- Short and relevant.
- No duplicate tags.

H2 HEADINGS:
- Exactly 10 headings.
- All headings must be unique.
- Each heading describes one concrete section.
- Logical progression.
- No generic "Conclusion" heading.
- ASCII punctuation only.
- No em dash or en dash.
- Normal hyphens only.

Return the JSON in ONE LINE.
Do not use Markdown code fences.
""".strip()

    user_prompt = f"""
FOCUS KEYWORD:
{keyword}

SPECIFIC ARTICLE ANGLE:
{specific_angle}

Plan the article now. The ten H2 headings should make it possible to write approximately 150-200 useful words per section.
""".strip()

    print("")
    print("=== PHASE 1: OUTLINE ===")

    response, actual_model = call_groq_with_fallback(
        api_key=api_key,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=OUTLINE_MAX_TOKENS,
        response_format={"type": "json_object"},
    )

    content = get_response_content(response)
    finish_reason = get_finish_reason(response)

    print(
        f"Outline response: "
        f"model={actual_model}, finish_reason={finish_reason}"
    )

    outline = extract_json_from_response(content, finish_reason=finish_reason)

    title = outline.get("title")
    if not isinstance(title, str):
        raise ValueError("Outline title must be a string.")

    title = title.strip()
    if not title:
        raise ValueError("Outline title is empty.")

    if keyword.lower() not in title.lower():
        raise ValueError(
            "Outline title does not contain the exact focus keyword."
        )

    meta_description = outline.get("meta_description")
    if not isinstance(meta_description, str):
        raise ValueError("Outline meta_description must be a string.")

    meta_description = meta_description.strip()
    if not meta_description:
        raise ValueError("Outline meta_description is empty.")

    tags = outline.get("tags")
    if not isinstance(tags, list):
        raise ValueError("Outline tags must be a list.")

    tags = [str(t).strip() for t in tags if str(t).strip()]

    if len(tags) != 3:
        raise ValueError("Outline must contain exactly 3 tags.")

    h2_headings = outline.get("h2_headings")
    if not isinstance(h2_headings, list):
        raise ValueError("Outline h2_headings must be a list.")

    cleaned_headings = []

    for heading in h2_headings:
        if not isinstance(heading, str):
            continue
        heading = clean_heading(heading)
        if heading:
            cleaned_headings.append(heading)

    if len(cleaned_headings) != REQUIRED_SECTION_COUNT:
        raise ValueError(
            "Outline must contain exactly "
            f"{REQUIRED_SECTION_COUNT} H2 headings. "
            f"Got {len(cleaned_headings)}."
        )

    normalized = [h.lower() for h in cleaned_headings]

    if len(set(normalized)) != len(normalized):
        raise ValueError("Outline contains duplicate H2 headings.")

    outline = {
        "title": title,
        "meta_description": meta_description,
        "tags": tags,
        "h2_headings": cleaned_headings,
    }

    print(f"Outline model: {actual_model}")
    print(f"Title: {title}")
    print(f"H2 count: {len(cleaned_headings)}")

    for index, heading in enumerate(cleaned_headings, start=1):
        print(f"  {index}. {heading}")

    return outline


def generate_section(
    api_key, title, h2_heading, section_number, total_sections=10,
):
    system_prompt = """
You are writing ONE section of a Home Organization article.

Your job is to write only the body of this one section.

Do NOT write the H2 heading.
Do NOT write a conclusion.
Do NOT mention other sections.
Do NOT summarize the article.
Do NOT mention that you are an AI.
Do NOT output JSON.
Do NOT use a Markdown code fence.

Write approximately 150-200 words.

Use:
- concrete details
- realistic measurements
- practical examples
- useful organization techniques
- specific actions
- realistic small-space constraints

The section must stand on its own while fitting naturally inside the larger article.

Return Markdown prose only.
""".strip()

    user_prompt = f"""
ARTICLE TITLE:
{title}

SECTION: {section_number} of {total_sections}

THIS SECTION'S H2 HEADING:
{h2_heading}

Write approximately 150-200 words for this section.

Use concrete details, measurements, and examples.

Do not write a conclusion.
Do not mention other sections.
Do not repeat the H2 heading.

Return Markdown text only.
""".strip()

    print(
        f"Generating section {section_number}/"
        f"{total_sections}: {h2_heading}"
    )

    response, actual_model = call_groq_with_fallback(
        api_key=api_key,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=ARTICLE_TEMPERATURE,
        max_tokens=SECTION_MAX_TOKENS,
        response_format=None,
    )

    content = get_response_content(response)
    finish_reason = get_finish_reason(response)
    content = clean_section_text(content)
    words = count_words(content)

    print(
        f"Section {section_number}: "
        f"model={actual_model}, "
        f"finish_reason={finish_reason}, "
        f"words={words}"
    )

    if finish_reason == "length":
        raise ValueError(
            f"Section {section_number} was truncated."
        )

    if not content:
        raise ValueError(f"Section {section_number} is empty.")

    if words < 100:
        raise ValueError(
            f"Section {section_number} is too short: {words} words."
        )

    if re.search(r"(?m)^\s*##\s+", content):
        raise ValueError(
            f"Section {section_number} unexpectedly contains an H2 heading."
        )

    return content


def clean_section_text(content):
    content = str(content).strip()
    content = re.sub(
        r"^```(?:markdown|md)?\s*", "", content, flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)
    content = re.sub(
        r"^\s*##[ \t]+[^\n]+\n+", "", content, count=1,
    )
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


def generate_all_sections(api_key, title, h2_headings):
    sections = []
    failed_section_indexes = []

    for index, heading in enumerate(h2_headings, start=1):
        success = False
        last_error = None

        for section_attempt in range(1, MAX_SECTION_RETRIES + 2):
            try:
                if section_attempt == 2:
                    print(
                        f"Retrying section {index} once: {heading}"
                    )

                section = generate_section(
                    api_key=api_key,
                    title=title,
                    h2_heading=heading,
                    section_number=index,
                    total_sections=len(h2_headings),
                )

                sections.append(section)
                success = True
                break

            except Exception as exc:
                last_error = exc
                print(
                    f"Section {index} attempt "
                    f"{section_attempt} failed: {exc}",
                    file=sys.stderr,
                )

                if section_attempt <= MAX_SECTION_RETRIES:
                    time.sleep(2)

        if not success:
            failed_section_indexes.append(index)
            print(
                f"Section {index} failed after "
                f"{MAX_SECTION_RETRIES + 1} attempts: {last_error}",
                file=sys.stderr,
            )

            if (len(failed_section_indexes)
                    >= MAX_FAILED_SECTIONS_BEFORE_PIPELINE_RESTART):
                raise RuntimeError(
                    "Two sections failed. Pipeline must restart. "
                    f"Failed sections: {failed_section_indexes}"
                )

            sections.append(None)

    if failed_section_indexes:
        raise RuntimeError(
            f"One or more sections failed: {failed_section_indexes}"
        )

    if len(sections) != len(h2_headings):
        raise RuntimeError("Section count does not match H2 count.")

    if any(s is None for s in sections):
        raise RuntimeError("At least one section is missing.")

    return sections


def clean_markdown(content):
    content = str(content).strip()
    content = re.sub(
        r"^```(?:markdown|md)?\s*", "", content, flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)
    content = re.sub(r"^\s*#\s+.+?\n+", "", content, count=1)
    content = re.sub(
        r"(?mi)^[ \t]*Tags:[ \t]*\[[^\r\n]*\][ \t]*\r?\n?",
        "",
        content,
    )
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


def assemble_article(
    title, meta_description, tags, h2_headings, sections,
):
    if len(h2_headings) != REQUIRED_SECTION_COUNT:
        raise ValueError("Assembly requires exactly 10 H2 headings.")

    if len(sections) != REQUIRED_SECTION_COUNT:
        raise ValueError("Assembly requires exactly 10 sections.")

    parts = []

    for heading, section in zip(h2_headings, sections):
        if not section:
            raise ValueError(f"Missing section for H2: {heading}")

        parts.append(
            f"## {heading}\n\n{section.strip()}"
        )

    content_markdown = "\n\n".join(parts).strip()
    content_markdown = clean_markdown(content_markdown)

    words = count_words(content_markdown)
    h2_count = count_h2(content_markdown)

    print("")
    print("=== PHASE 3: ASSEMBLY ===")
    print(f"Assembled word count: {words}")
    print(f"Assembled H2 count: {h2_count}")

    if h2_count != REQUIRED_SECTION_COUNT:
        raise ValueError(
            "Assembly validation failed: expected exactly "
            f"{REQUIRED_SECTION_COUNT} H2, got {h2_count}."
        )

    if words < MIN_ACCEPTABLE_WORDS:
        raise ValueError(
            "Assembly validation failed: "
            f"{words} words below acceptable minimum "
            f"of {MIN_ACCEPTABLE_WORDS}."
        )

    if words > MAX_WORDS:
        raise ValueError(
            f"Assembly validation failed: {words} words exceeds "
            f"maximum of {MAX_WORDS}."
        )

    return (content_markdown, words, h2_count)


def shorten_title(title, keyword):
    title = str(title).strip()

    if len(title) <= MAX_TITLE_LENGTH:
        return title

    trimmed = title[:MAX_TITLE_LENGTH].rstrip()
    trimmed = re.sub(r"[\s:;\-,]+$", "", trimmed)

    if keyword and keyword.lower() not in trimmed.lower():
        candidate = f"{keyword} - Small Space Guide"

        if len(candidate) <= MAX_TITLE_LENGTH:
            trimmed = candidate

    return trimmed


def shorten_meta(meta):
    meta = str(meta).strip()

    if MIN_META_LENGTH <= len(meta) <= MAX_META_LENGTH:
        return meta

    if len(meta) > MAX_META_LENGTH:
        trimmed = meta[:MAX_META_LENGTH].rstrip()
        last_period = trimmed.rfind(". ")

        if last_period >= MIN_META_LENGTH:
            trimmed = trimmed[:last_period + 1].strip()
        else:
            last_space = trimmed.rfind(" ")

            if last_space >= MIN_META_LENGTH:
                trimmed = trimmed[:last_space].rstrip()

        if not trimmed.endswith((".", "!", "?")):
            trimmed += "."

        return trimmed[:MAX_META_LENGTH].strip()

    additions = [
        " Practical ideas for everyday homes.",
        " Simple ideas for a more organized home.",
    ]

    result = meta

    for addition in additions:
        if len(result) >= MIN_META_LENGTH:
            break

        candidate = result.rstrip(".") + addition

        if len(candidate) <= MAX_META_LENGTH:
            result = candidate

    return result[:MAX_META_LENGTH].strip()


def count_words(text):
    plain = re.sub(r"`[^`]+`", "", str(text))
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", plain)
    plain = re.sub(r"\[[^\]]*\]\([^)]*\)", "", plain)

    return len(
        re.findall(r"\b[\w'-]+\b", plain, flags=re.UNICODE)
    )


def count_h2(content):
    return len(
        re.findall(r"^\s*##\s+\S+", str(content), re.MULTILINE)
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
        raise ValueError(
            "At least four H2 sections are required "
            "for image-query generation."
        )

    selected_sections = sections[:4]
    section_payload = []

    for index, section in enumerate(selected_sections, start=1):
        body = re.sub(r"\n{3,}", "\n\n", section["body"]).strip()
        body = body[:500]
        section_payload.append(
            f"SECTION {index}\n"
            f"H2: {section['heading']}\n"
            f"CONTENT: {body}\n"
        )

    sections_text = "\n".join(section_payload)

    system_prompt = """
You are a visual content editor for a Home Organization website.

Create exactly 5 highly relevant and visually distinct Pexels search queries.

QUERY 1: Hero image for the whole article. Wide editorial photo of the relevant room.

QUERIES 2-5: One image query for each of the first four H2 sections.

RULES:
- Exactly 5 unique queries.
- 5-14 words per query.
- Concrete visual nouns.
- Describe photographable scenes.
- No photographer names.
- No generic SEO keyword stuffing.
- No duplicate scenes.
- No image URLs.
- No Markdown.

Return ONLY valid JSON. Return in ONE LINE.

{
  "image_queries": ["query 1", "query 2", "query 3", "query 4", "query 5"]
}
""".strip()

    user_prompt = (
        f"ARTICLE TITLE:\n{title}\n\n"
        f"{sections_text}\n\n"
        "Return exactly 5 unique queries."
    )

    print("")
    print("=== IMAGE QUERIES ===")

    response, actual_model = call_groq_with_fallback(
        api_key=api_key,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
        max_tokens=IMAGE_QUERY_MAX_TOKENS,
        response_format={"type": "json_object"},
    )

    content = get_response_content(response)
    finish_reason = get_finish_reason(response)

    result = extract_json_from_response(content, finish_reason=finish_reason)

    raw_queries = result.get("image_queries")

    if not isinstance(raw_queries, list):
        raise ValueError("image_queries must be a list.")

    image_queries = []

    for query in raw_queries:
        if not isinstance(query, str):
            continue
        query = query.strip()
        if query and query not in image_queries:
            image_queries.append(query)

    if len(image_queries) != 5:
        raise ValueError(
            "Exactly 5 unique image queries are required."
        )

    print(f"Image-query model: {actual_model}")

    for index, query in enumerate(image_queries, start=1):
        label = "HERO" if index == 1 else f"H2 #{index - 1}"
        print(f"  {index}. [{label}] {query}")

    return image_queries


def save_article(article):
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")

    with temp_path.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(article, file, ensure_ascii=False, indent=2)
        file.write("\n")

    temp_path.replace(ARTICLE_PATH)


def generate_article_pipeline(api_key, keyword, specific_angle):
    outline = generate_outline(
        api_key=api_key,
        keyword=keyword,
        specific_angle=specific_angle,
    )

    title = outline["title"]
    meta_description = outline["meta_description"]
    tags = outline["tags"]
    h2_headings = outline["h2_headings"]

    print("")
    print("=== PHASE 2: SECTIONS ===")

    sections = generate_all_sections(
        api_key=api_key,
        title=title,
        h2_headings=h2_headings,
    )

    (content_markdown, word_count, h2_count) = assemble_article(
        title=title,
        meta_description=meta_description,
        tags=tags,
        h2_headings=h2_headings,
        sections=sections,
    )

    title = shorten_title(title, keyword)
    meta_description = shorten_meta(meta_description)

    if keyword.lower() not in title.lower():
        raise ValueError(
            "Final title does not contain the focus keyword."
        )

    final_word_count = count_words(content_markdown)
    final_h2_count = count_h2(content_markdown)

    if final_word_count < MIN_ACCEPTABLE_WORDS:
        raise ValueError(
            f"Final article is too short: {final_word_count} words."
        )

    if final_h2_count != REQUIRED_SECTION_COUNT:
        raise ValueError(
            "Final article must contain exactly "
            f"{REQUIRED_SECTION_COUNT} H2 headings; "
            f"got {final_h2_count}."
        )

    return {
        "title": title,
        "meta_description": meta_description,
        "tags": tags,
        "content_markdown": content_markdown,
        "word_count": final_word_count,
        "h2_count": final_h2_count,
        "h2_headings": h2_headings,
    }


def main():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        print("ERROR: GROQ_API_KEY is missing.", file=sys.stderr)
        return 1

    try:
        (keyword, rows, fieldnames, keyword_col, status_col) = (
            get_first_pending_keyword()
        )
    except Exception as exc:
        print(f"ERROR loading keywords: {exc}", file=sys.stderr)
        return 1

    print("")
    print("================================================")
    print("AUTO BLOG - SECTIONED ARTICLE GENERATION")
    print("================================================")
    print(f"Keyword: {keyword}")
    print(f"Primary model: {GROQ_MODEL}")
    print(f"Fallback model: {FALLBACK_GROQ_MODEL}")

    try:
        mark_keyword_processing(
            keyword, rows, fieldnames, keyword_col, status_col,
        )
        print("Keyword status: processing")
    except Exception as exc:
        print(f"ERROR changing keyword status: {exc}", file=sys.stderr)
        return 1

    try:
        specific_angle = pick_specific_angle(api_key, keyword)
        print(f"Specific angle: {specific_angle}")

        pipeline_result = None
        last_pipeline_error = None

        for pipeline_attempt in range(1, MAX_PIPELINE_ATTEMPTS + 1):
            print("")
            print("================================================")
            print(
                f"PIPELINE ATTEMPT "
                f"{pipeline_attempt}/{MAX_PIPELINE_ATTEMPTS}"
            )
            print("================================================")

            try:
                pipeline_result = generate_article_pipeline(
                    api_key=api_key,
                    keyword=keyword,
                    specific_angle=specific_angle,
                )
                print(
                    f"Pipeline attempt {pipeline_attempt} succeeded."
                )
                break

            except Exception as exc:
                last_pipeline_error = exc
                print(
                    f"Pipeline attempt {pipeline_attempt} failed: "
                    f"{exc}",
                    file=sys.stderr,
                )

                if pipeline_attempt < MAX_PIPELINE_ATTEMPTS:
                    print(
                        "Restarting the entire article "
                        "pipeline from Phase 1..."
                    )
                    time.sleep(3)

        if pipeline_result is None:
            raise RuntimeError(
                "All complete pipeline attempts failed. "
                f"Last error: {last_pipeline_error}"
            )

        title = pipeline_result["title"]
        meta_description = pipeline_result["meta_description"]
        tags = pipeline_result["tags"]
        content_markdown = pipeline_result["content_markdown"]
        word_count = pipeline_result["word_count"]
        h2_count = pipeline_result["h2_count"]
        h2_headings = pipeline_result["h2_headings"]

        image_queries = generate_image_queries(
            api_key=api_key,
            title=title,
            content_markdown=content_markdown,
        )

        if len(image_queries) != 5:
            raise ValueError(
                "Image-query generation did not return exactly 5 queries."
            )

        slug = slugify(title)

        if not slug:
            raise ValueError("Could not generate a valid slug.")

        final_word_count = count_words(content_markdown)
        final_h2_count = count_h2(content_markdown)

        if final_word_count < MIN_WORDS:
            print(
                "WARNING: final article is below the "
                f"preferred {MIN_WORDS}-word target: "
                f"{final_word_count} words."
            )

        if final_word_count < MIN_ACCEPTABLE_WORDS:
            raise ValueError(
                "Final article is below the hard acceptable "
                f"minimum of {MIN_ACCEPTABLE_WORDS} words."
            )

        if final_word_count > MAX_WORDS:
            raise ValueError(
                f"Final article exceeds maximum "
                f"{MAX_WORDS} words: {final_word_count}."
            )

        if final_h2_count != REQUIRED_SECTION_COUNT:
            raise ValueError(
                "Final article must have exactly "
                f"{REQUIRED_SECTION_COUNT} H2 headings."
            )

        article = {
            "keyword": keyword,
            "specific_angle": specific_angle,
            "title": title,
            "slug": slug,
            "meta_description": meta_description,
            "content_markdown": content_markdown,
            "image_queries": image_queries,
            "tags": tags,
            "h2_headings": h2_headings,
            "word_count": final_word_count,
            "h2_count": final_h2_count,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        save_article(article)

        print("")
        print("================================================")
        print("ARTICLE GENERATED SUCCESSFULLY")
        print("================================================")
        print(f"Keyword: {keyword}")
        print(f"Title: {title}")
        print(f"Slug: {slug}")
        print(f"Words: {final_word_count}")
        print(f"H2: {final_h2_count}")
        print(f"Title length: {len(title)}")
        print(f"Meta length: {len(meta_description)}")
        print(f"Tags: {', '.join(tags)}")
        print("Image queries: 5")
        print(f"Saved: {ARTICLE_PATH}")

        return 0

    except Exception as exc:
        print("", file=sys.stderr)
        print("================================================", file=sys.stderr)
        print("ARTICLE GENERATION FAILED", file=sys.stderr)
        print("================================================", file=sys.stderr)
        print(f"Error: {exc}", file=sys.stderr)

        try:
            mark_keyword_pending(keyword)
            print(f"Keyword returned to pending: {keyword}")
        except Exception as reset_exc:
            print(
                f"ERROR resetting keyword status: {reset_exc}",
                file=sys.stderr,
            )

        return 1


if __name__ == "__main__":
    sys.exit(main())
