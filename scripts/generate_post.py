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
FALLBACK_GROQ_MODEL = os.getenv(
    "FALLBACK_GROQ_MODEL",
    "openai/gpt-oss-20b",
)

MAX_RETRIES = 3

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

FAQ_MIN_ITEMS = 4
FAQ_MAX_ITEMS = 6
MAX_SECTION_RETRIES = 1
MAX_FAILED_SECTIONS_BEFORE_PIPELINE_RESTART = 2
MAX_PIPELINE_ATTEMPTS = 2

MAX_TITLE_LENGTH = 68
MIN_META_LENGTH = 140
MAX_META_LENGTH = 158


class TruncatedJSONError(ValueError):
    pass


class GroqJSONError(RuntimeError):
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


def get_exception_message(exc):
    try:
        return str(exc)
    except Exception:
        return repr(exc)


def is_json_validation_error(exc):
    message = get_exception_message(exc).lower()
    status_code = get_exception_status_code(exc)

    if status_code != 400:
        return False

    patterns = [
        "json_validate_failed",
        "json validation",
        "json validation failed",
        "response_format",
        "invalid json",
        "invalid response format",
    ]

    return any(p in message for p in patterns)


def get_finish_reason(response):
    try:
        if not response.choices:
            return None
        return getattr(
            response.choices[0], "finish_reason", None,
        )
    except Exception:
        return None


def get_response_content(response):
    if not response.choices:
        raise ValueError("No choices returned by Groq.")

    message = response.choices[0].message
    content = getattr(message, "content", None)

    if content is None:
        raise ValueError("Groq returned empty message content.")

    if not isinstance(content, str):
        raise ValueError("Groq response content is not a string.")

    if not content.strip():
        raise ValueError("Groq returned blank message content.")

    return content


def get_response_model(response, requested_model=None):
    model = getattr(response, "model", None)
    if model:
        return str(model)
    return requested_model or "unknown"


def log_response_metadata(
    response, requested_model=None, label="Groq response",
):
    actual_model = get_response_model(response, requested_model)
    finish_reason = get_finish_reason(response)
    usage = getattr(response, "usage", None)
    completion_tokens = None

    if usage is not None:
        completion_tokens = getattr(
            usage, "completion_tokens", None,
        )

    print(
        f"{label}: "
        f"model={actual_model}, "
        f"finish_reason={finish_reason}, "
        f"completion_tokens={completion_tokens}"
    )


JSON_RULES = """
JSON OUTPUT RULES - FOLLOW EXACTLY:

1. Return ONLY one JSON object.
2. Do not include any text before the JSON object.
3. Do not include any text after the JSON object.
4. Do not use Markdown code fences.
5. Do not use ```json.
6. Use double quotes for every JSON string.
7. Never use single quotes for JSON strings.
8. Do not use trailing commas.
9. Escape quotation marks inside strings correctly.
10. Escape backslashes correctly.
11. Keep newline characters inside strings valid.
12. Do not add comments.
13. Do not add explanations.
14. Do not add headings outside the JSON object.
15. The response must begin with { and end with }.
""".strip()


def build_json_system_prompt(base_prompt):
    return (
        base_prompt.strip()
        + "\n\n"
        + JSON_RULES
    ).strip()


def strip_code_fences(text):
    if not isinstance(text, str):
        raise ValueError("Response is not a string.")

    text = text.strip()
    if not text:
        return ""

    text = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\s*```\s*$", "", text)

    return text.strip()


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


def try_json_loads(value):
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise ValueError("JSON response must be an object.")
        return result
    except json.JSONDecodeError:
        return None


def repair_common_json_issues(text):
    repaired = text.strip()
    repaired = repaired.replace("\ufeff", "")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def extract_json_safe(text, finish_reason=None):
    if not isinstance(text, str):
        raise ValueError("Model response must be a string.")

    original = text.strip()
    if not original:
        raise ValueError("Model returned an empty response.")

    result = try_json_loads(original)
    if result is not None:
        return result

    cleaned = strip_code_fences(original)
    result = try_json_loads(cleaned)
    if result is not None:
        return result

    try:
        balanced = extract_balanced_json_object(cleaned)
        result = try_json_loads(balanced)
        if result is not None:
            return result
    except TruncatedJSONError:
        if finish_reason == "length":
            raise TruncatedJSONError(
                "Groq returned finish_reason=length "
                "and JSON truncated."
            )
    except ValueError:
        pass

    repaired = repair_common_json_issues(cleaned)
    result = try_json_loads(repaired)
    if result is not None:
        return result

    try:
        balanced = extract_balanced_json_object(repaired)
        result = try_json_loads(balanced)
        if result is not None:
            return result
    except TruncatedJSONError as exc:
        if finish_reason == "length":
            raise TruncatedJSONError(
                "Groq finish_reason=length, "
                "JSON truncated after repair."
            ) from exc

    preview = original[:500]
    raise ValueError(
        f"Unable to extract valid JSON. Preview: {preview!r}"
    )


extract_json_from_response = extract_json_safe


def groq_request(
    client, model, messages, temperature, max_tokens, use_json_mode,
):
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if use_json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    return client.chat.completions.create(**kwargs)


def call_model_with_retries(
    client,
    model,
    messages,
    temperature,
    max_tokens,
    use_json_mode,
    label,
):
    retryable_codes = {429, 500, 502, 503, 504}
    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            mode_name = "JSON mode" if use_json_mode else "plain mode"

            print(
                f"{label}: "
                f"model={model}, "
                f"mode={mode_name}, "
                f"attempt={attempt}/{MAX_RETRIES}"
            )

            response = groq_request(
                client=client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                use_json_mode=use_json_mode,
            )

            log_response_metadata(
                response, requested_model=model, label=label,
            )
            return response

        except Exception as exc:
            last_exception = exc
            status_code = get_exception_status_code(exc)

            print(
                f"{label} failed: "
                f"status={status_code}, error={exc}",
                file=sys.stderr,
            )

            if use_json_mode and is_json_validation_error(exc):
                raise GroqJSONError(
                    "Groq JSON mode failed with "
                    "json_validate_failed."
                ) from exc

            if status_code == 400 and not use_json_mode:
                raise

            if status_code == 429:
                raise

            if (
                status_code is not None
                and status_code not in retryable_codes
            ):
                raise

            if attempt >= MAX_RETRIES:
                break

            delay = min(2 ** (attempt - 1), 15)
            print(f"Retrying in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(
        f"Groq model '{model}' failed after "
        f"{MAX_RETRIES} attempts: {last_exception}"
    ) from last_exception


def local_angle_fallback(keyword):
    angles = [
        f"small-space {keyword} solution using vertical storage",
        f"renter-friendly {keyword} solution without permanent changes",
        f"practical {keyword} setup for a small everyday home",
        f"{keyword} organization using measured zones and containers",
        f"budget-friendly {keyword} organization for limited storage",
    ]
    return angles[0]


def local_outline_fallback(keyword, specific_angle):
    title = f"{keyword} - A Practical Small Space Guide"

    if len(title) > MAX_TITLE_LENGTH:
        title = f"{keyword} - Small Space Guide"

    meta = (
        f"Practical {keyword} ideas with simple measurements, "
        f"storage zones, and realistic steps for a more "
        f"organized home."
    )

    if len(meta) < MIN_META_LENGTH:
        meta += " Designed for everyday spaces and simple routines."

    meta = meta[:MAX_META_LENGTH]

    headings = [
        f"Assess Your Space for {keyword}",
        "Measure the Area Before Buying Anything",
        "Create Zones for the Items You Use Most",
        "Use Vertical Space Without Making Clutter",
        "Choose Containers That Match the Space",
        "Make Frequently Used Items Easy to Reach",
        "Handle Awkward Corners and Narrow Areas",
        "Build a Simple Routine That Stays Organized",
        "Avoid Common Storage Mistakes",
        "Create a Maintenance Plan That Takes Minutes",
    ]

    tags = [keyword, "home organization", "small spaces"]

    return {
        "title": title,
        "meta_description": meta,
        "tags": tags,
        "h2_headings": headings,
    }


def local_section_fallback(
    title, heading, section_number, keyword,
):
    keyword_phrase = (
        keyword.strip() if keyword else "this home project"
    )

    opening_keyword_paragraphs = {
        1: (
            f"Looking at {keyword_phrase} from a practical angle, "
            f"the first decision is to understand exactly what the "
            f"space needs to hold before buying anything. Measure "
            f"the available width, depth, and height with a tape "
            f"measure. A useful starting point is to leave about "
            f"5 to 8 centimeters of working clearance around items "
            f"you use every day. Group similar belongings together "
            f"and keep the most-used group within easy reach. For "
            f"example, if the area is about 90 centimeters wide, "
            f"divide it into two or three clear zones rather than "
            f"filling every centimeter. This approach to "
            f"{keyword_phrase} makes the system easier to "
            f"understand and easier to maintain. One common "
            f"mistake is organizing items by appearance alone. "
            f"Instead, organize according to how often each item "
            f"is used and where the item is naturally needed."
        ),
        2: (
            f"When approaching {keyword_phrase}, measurements "
            f"come first. A shelf that is 60 centimeters wide may "
            f"look generous, but doors, handles, pipes, or trim "
            f"can reduce usable space by several centimeters. "
            f"Leave roughly 2 to 5 centimeters of clearance where "
            f"doors or drawers need to move. Use the measurements "
            f"to decide what belongs in the area and what should "
            f"live somewhere else. A simple container works well "
            f"when it is sized to the shelf instead of being "
            f"chosen first. Another useful rule for "
            f"{keyword_phrase} is to keep heavy objects lower "
            f"and light objects higher. This reduces awkward "
            f"handling and makes the arrangement safer. Avoid "
            f"buying several matching containers before testing "
            f"the layout with one."
        ),
        3: (
            f"Divide the area into clear zones so every category "
            f"has a predictable home. For {keyword_phrase}, a "
            f"120 centimeter run could contain a 40 centimeter "
            f"daily-use zone, a 40 centimeter reserve zone, and a "
            f"40 centimeter occasional zone. The exact "
            f"measurements should follow the available space "
            f"rather than a fixed formula. Keep items used every "
            f"day between waist and shoulder height whenever "
            f"possible. Labels help when several categories look "
            f"similar, but they should remain short and easy to "
            f"read. A system with three obvious zones is often "
            f"easier to maintain than one with ten tiny "
            f"categories."
        ),
    }

    default_template = (
        f"Applying {keyword_phrase} to this section means "
        f"focusing on the smallest workable change first. "
        f"Observe how the space behaves for several days. "
        f"If an item repeatedly ends up outside its assigned "
        f"zone, that is useful feedback rather than a failure. "
        f"Move the zone closer to where the item is actually "
        f"used, or make the container easier to access. "
        f"The goal of {keyword_phrase} is a system that "
        f"reduces decisions, not one that only looks tidy "
        f"immediately after organizing. Keep the number of "
        f"categories small so the system stays easy to follow "
        f"during busy weeks. Re-check the arrangement every "
        f"few months and adjust for seasonal changes."
    )

    opening = opening_keyword_paragraphs.get(
        section_number,
        default_template,
    )

    second_paragraph = (
        f"Focus this part of {keyword_phrase} on \"{heading}\". "
        f"Start with one small adjustment and watch how the "
        f"space behaves for several days. If something is not "
        f"working, adjust the placement rather than adding more "
        f"containers. The goal is a simple, repeatable routine "
        f"that stays organized without daily effort."
    )

    return "\n\n".join([opening, second_paragraph])


def local_image_query_fallback(title, content_markdown):
    sections = extract_h2_sections(content_markdown)

    queries = ["organized home interior wide editorial storage room"]

    for section in sections[:4]:
        heading = section["heading"]

        clean = re.sub(r"[^A-Za-z0-9 ]+", " ", heading)
        clean = re.sub(r"\s+", " ", clean).strip()

        query = (
            f"organized home {clean.lower()} storage interior"
        )

        queries.append(" ".join(query.split()[:14]))

    while len(queries) < 5:
        queries.append("organized small home storage interior")

    return queries[:5]


def call_json_with_four_layers(
    api_key,
    messages,
    temperature,
    max_tokens,
    local_fallback_factory,
    operation_name,
):
    client = Groq(api_key=api_key)

    models = [
        ("PRIMARY", GROQ_MODEL),
        ("FALLBACK", FALLBACK_GROQ_MODEL),
    ]

    last_exception = None

    for model_index, (model_label, model) in enumerate(models):

        try:
            response = call_model_with_retries(
                client=client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                use_json_mode=True,
                label=(
                    f"{operation_name} "
                    f"Layer "
                    f"{'1' if model_index == 0 else '3'} "
                    f"{model_label}"
                ),
            )

            content = get_response_content(response)
            finish_reason = get_finish_reason(response)

            result = extract_json_safe(
                content, finish_reason=finish_reason,
            )

            print(f"{operation_name}: JSON layer succeeded.")

            return (
                result,
                get_response_model(response, model),
                (
                    "primary-json"
                    if model_index == 0
                    else "fallback-json"
                ),
            )

        except Exception as exc:
            last_exception = exc
            print(
                f"{operation_name}: JSON layer failed: {exc}",
                file=sys.stderr,
            )

        try:
            print(
                f"{operation_name}: Trying plain-text JSON "
                f"extraction with {model}."
            )

            response = call_model_with_retries(
                client=client,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                use_json_mode=False,
                label=(
                    f"{operation_name} "
                    f"Layer "
                    f"{'2' if model_index == 0 else '4'} "
                    f"{model_label}"
                ),
            )

            content = get_response_content(response)
            finish_reason = get_finish_reason(response)

            result = extract_json_safe(
                content, finish_reason=finish_reason,
            )

            print(
                f"{operation_name}: "
                "plain-text JSON layer succeeded."
            )

            return (
                result,
                get_response_model(response, model),
                (
                    "primary-plain"
                    if model_index == 0
                    else "fallback-plain"
                ),
            )

        except Exception as exc:
            last_exception = exc
            print(
                f"{operation_name}: plain-text layer failed: {exc}",
                file=sys.stderr,
            )

    print(
        f"{operation_name}: ALL GROQ LAYERS FAILED. "
        "Using local fallback.",
        file=sys.stderr,
    )

    try:
        result = local_fallback_factory()

        if not isinstance(result, dict):
            raise ValueError(
                "Local fallback did not return a dict."
            )

        return (result, "local-fallback", "local")

    except Exception as exc:
        raise RuntimeError(
            f"{operation_name} failed on all four Groq "
            f"layers and local fallback. "
            f"Last Groq error: {last_exception}; "
            f"local error: {exc}"
        ) from exc


def pick_specific_angle(api_key, keyword):
    base_prompt = """
You are an editorial strategist for a Home Organization website.

Generate exactly 5 narrow article angles for the supplied keyword,
then select the most specific and useful one.

Prefer:
- a specific room
- a specific storage problem
- a specific constraint
- measurements
- renter limitations
- a concrete before/after situation

The JSON object must contain exactly:
{
  "angles": [
    "angle 1",
    "angle 2",
    "angle 3",
    "angle 4",
    "angle 5"
  ],
  "selected_angle": "selected angle"
}
"""

    system_prompt = build_json_system_prompt(base_prompt)

    user_prompt = f"""
Focus keyword:
{keyword}

Return exactly 5 unique narrow angles.
Select one of the five angles as selected_angle.
""".strip()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    print("")
    print("=== ARTICLE ANGLE ===")

    result, actual_model, layer = call_json_with_four_layers(
        api_key=api_key,
        messages=messages,
        temperature=0.5,
        max_tokens=800,
        local_fallback_factory=lambda: {
            "angles": [
                local_angle_fallback(keyword),
                f"{keyword} for small homes",
                f"{keyword} for renters",
                f"budget {keyword} ideas",
                f"practical {keyword} system",
            ],
            "selected_angle": local_angle_fallback(keyword),
        },
        operation_name="ANGLE",
    )

    angles = result.get("angles")

    if not isinstance(angles, list):
        raise ValueError(
            "Angle response must contain an angles list."
        )

    angles = [
        str(angle).strip()
        for angle in angles
        if str(angle).strip()
    ]

    unique_angles = []

    for angle in angles:
        if angle not in unique_angles:
            unique_angles.append(angle)

    if len(unique_angles) < 5:
        raise ValueError(
            "Angle generator returned fewer than "
            "5 unique angles."
        )

    angles = unique_angles[:5]

    selected_angle = result.get("selected_angle")

    if not isinstance(selected_angle, str):
        selected_angle = angles[0]

    selected_angle = selected_angle.strip()

    if selected_angle not in angles:
        selected_angle = angles[0]

    print(f"Angle model: {actual_model}")
    print(f"Angle strategy: {layer}")
    print("Generated angles:")

    for index, angle in enumerate(angles, start=1):
        marker = (
            " <-- SELECTED"
            if angle == selected_angle
            else ""
        )
        print(f"{index}. {angle}{marker}")

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


def build_article_messages(keyword, specific_angle):
    system_prompt = """
You are an expert editorial planner for a Home Organization website.

Create the complete outline for ONE practical article.

The output must contain exactly these fields:

{
  "title": "string",
  "meta_description": "string",
  "tags": ["string", "string", "string"],
  "h2_headings": [
    "string", "string", "string", "string", "string",
    "string", "string", "string", "string", "string"
  ]
}

HARD CONTENT RULES:

TITLE:
- Must contain the exact focus keyword.
- Maximum 68 characters.
- Clear and specific.

META DESCRIPTION:
- 140-158 characters.
- Natural English.

TAGS:
- Exactly 3 tags.
- No duplicate tags.

H2 HEADINGS:
- Exactly 10 headings.
- All headings unique.
- ASCII punctuation only.
- No em dash, no en dash.

Do not write the article.
Only create the outline.
""".strip()

    system_prompt = build_json_system_prompt(system_prompt)

    user_prompt = f"""
FOCUS KEYWORD:
{keyword}

SPECIFIC ARTICLE ANGLE:
{specific_angle}

Create the outline now.
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def validate_outline(outline, keyword, actual_model):
    if not isinstance(outline, dict):
        raise ValueError("Outline is not a JSON object.")

    title = outline.get("title")
    if not isinstance(title, str):
        raise ValueError("Outline title must be a string.")

    title = title.strip()
    if not title:
        raise ValueError("Outline title is empty.")

    if keyword.lower() not in title.lower():
        raise ValueError(
            "Outline title does not contain the "
            "exact focus keyword."
        )

    meta_description = outline.get("meta_description")
    if not isinstance(meta_description, str):
        raise ValueError(
            "Outline meta_description must be a string."
        )

    meta_description = meta_description.strip()
    if not meta_description:
        raise ValueError(
            "Outline meta_description is empty."
        )

    tags = outline.get("tags")
    if not isinstance(tags, list):
        raise ValueError("Outline tags must be a list.")

    tags = [
        str(tag).strip()
        for tag in tags
        if str(tag).strip()
    ]

    if len(tags) != 3:
        raise ValueError(
            "Outline must contain exactly 3 tags."
        )

    if len({tag.lower() for tag in tags}) != 3:
        raise ValueError("Outline tags must be unique.")

    h2_headings = outline.get("h2_headings")
    if not isinstance(h2_headings, list):
        raise ValueError(
            "Outline h2_headings must be a list."
        )

    cleaned_headings = []

    for heading in h2_headings:
        if not isinstance(heading, str):
            continue
        heading = clean_heading(heading)
        if heading:
            cleaned_headings.append(heading)

    if len(cleaned_headings) != REQUIRED_SECTION_COUNT:
        raise ValueError(
            f"Outline must contain exactly "
            f"{REQUIRED_SECTION_COUNT} H2 headings. "
            f"Got {len(cleaned_headings)}."
        )

    normalized = [h.lower() for h in cleaned_headings]

    if len(set(normalized)) != len(normalized):
        raise ValueError(
            "Outline contains duplicate H2 headings."
        )

    return {
        "title": title,
        "meta_description": meta_description,
        "tags": tags,
        "h2_headings": cleaned_headings,
    }


def generate_outline(api_key, keyword, specific_angle):
    print("")
    print("=== PHASE 1: OUTLINE ===")

    messages = build_article_messages(
        keyword=keyword,
        specific_angle=specific_angle,
    )

    result, actual_model, layer = call_json_with_four_layers(
        api_key=api_key,
        messages=messages,
        temperature=0.4,
        max_tokens=OUTLINE_MAX_TOKENS,
        local_fallback_factory=lambda: local_outline_fallback(
            keyword, specific_angle,
        ),
        operation_name="OUTLINE",
    )

    outline = validate_outline(
        outline=result,
        keyword=keyword,
        actual_model=actual_model,
    )

    print(f"Outline model: {actual_model}")
    print(f"Outline strategy: {layer}")
    print(f"Title: {outline['title']}")
    print(f"H2 count: {len(outline['h2_headings'])}")

    for index, heading in enumerate(
        outline["h2_headings"], start=1,
    ):
        print(f"  {index}. {heading}")

    return outline


def generate_section(
    api_key, title, h2_heading, section_number,
    keyword, total_sections=10,
):
    system_prompt = """
You are writing ONE section of a Home Organization article.

Do NOT write the H2 heading.
Do NOT write a conclusion.
Do NOT mention other sections.
Do NOT summarize.
Do NOT mention AI.
Do NOT output JSON.
Do NOT use code fences.

Write approximately 150-200 words.

Use:
- concrete details
- realistic measurements
- practical examples
- specific actions
- common mistakes

Return Markdown prose only.
""".strip()

    user_prompt = f"""
ARTICLE TITLE:
{title}

SECTION: {section_number} of {total_sections}

THIS SECTION'S H2 HEADING:
{h2_heading}

Write approximately 150-200 words for this section.

Do not write a conclusion.
Do not mention other sections.
Do not repeat the H2 heading.
Do not output JSON.

Return Markdown text only.
""".strip()

    print(
        f"Generating section {section_number}/"
        f"{total_sections}: {h2_heading}"
    )

    client = Groq(api_key=api_key)

    models = [
        ("PRIMARY", GROQ_MODEL),
        ("FALLBACK", FALLBACK_GROQ_MODEL),
    ]

    last_error = None

    for model_label, model in models:
        try:
            response = call_model_with_retries(
                client=client,
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                temperature=ARTICLE_TEMPERATURE,
                max_tokens=SECTION_MAX_TOKENS,
                use_json_mode=False,
                label=(
                    f"SECTION {section_number} "
                    f"{model_label}"
                ),
            )

            content = get_response_content(response)
            finish_reason = get_finish_reason(response)
            content = clean_section_text(content)
            words = count_words(content)

            actual_model = get_response_model(
                response, model,
            )

            print(
                f"Section {section_number}: "
                f"model={actual_model}, "
                f"finish_reason={finish_reason}, "
                f"words={words}"
            )

            if finish_reason == "length":
                raise ValueError(
                    f"Section {section_number} truncated."
                )

            if not content:
                raise ValueError(
                    f"Section {section_number} empty."
                )

            if words < 100:
                raise ValueError(
                    f"Section {section_number} too short: "
                    f"{words} words."
                )

            if re.search(r"(?m)^\s*##\s+", content):
                raise ValueError(
                    f"Section {section_number} contains "
                    "an H2 heading."
                )

            return content

        except Exception as exc:
            last_error = exc
            print(
                f"Section {section_number} with {model} "
                f"failed: {exc}",
                file=sys.stderr,
            )

    print(
        f"Section {section_number}: Groq unavailable. "
        "Using local fallback.",
        file=sys.stderr,
    )

    content = local_section_fallback(
        title=title,
        heading=h2_heading,
        section_number=section_number,
        keyword=keyword,
    )

    if count_words(content) < 100:
        raise RuntimeError(
            f"Local fallback for section "
            f"{section_number} too short. "
            f"Last Groq error: {last_error}"
        )

    return content


def generate_all_sections(
    api_key, title, h2_headings, keyword,
):
    sections = []
    failed_section_indexes = []

    for index, heading in enumerate(h2_headings, start=1):
        success = False
        last_error = None

        for section_attempt in range(
            1, MAX_SECTION_RETRIES + 2,
        ):
            try:
                if section_attempt == 2:
                    print(
                        f"Retrying section {index}: {heading}"
                    )

                section = generate_section(
                    api_key=api_key,
                    title=title,
                    h2_heading=heading,
                    section_number=index,
                    keyword=keyword,
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
                f"{MAX_SECTION_RETRIES + 1} attempts: "
                f"{last_error}",
                file=sys.stderr,
            )

            if (
                len(failed_section_indexes)
                >= MAX_FAILED_SECTIONS_BEFORE_PIPELINE_RESTART
            ):
                raise RuntimeError(
                    "Two or more sections failed. "
                    "Pipeline must restart. "
                    f"Failed sections: "
                    f"{failed_section_indexes}"
                )

            sections.append(None)

    if failed_section_indexes:
        raise RuntimeError(
            f"One or more sections failed: "
            f"{failed_section_indexes}"
        )

    if len(sections) != len(h2_headings):
        raise RuntimeError(
            "Section count does not match H2 count."
        )

    if any(section is None for section in sections):
        raise RuntimeError(
            "At least one section is missing."
        )

    return sections



def local_faq_fallback(keyword, title):
    topic = keyword.strip() or "this space"
    return [
        {"question": f"How should I start organizing {topic}?",
         "answer": "Start by measuring the space, grouping items by use, and choosing one small zone to organize first. Test the layout before buying several containers."},
        {"question": f"What should I measure before organizing {topic}?",
         "answer": "Measure width, depth, height, door or drawer clearance, and fixed obstacles such as pipes, trim, or handles. Record usable measurements rather than room size alone."},
        {"question": f"How many storage zones should I create for {topic}?",
         "answer": "Three broad zones are a practical starting point: daily-use items, reserve supplies, and occasional items. Adjust the number to the space instead of forcing a fixed layout."},
        {"question": f"How can I keep {topic} organized after the first cleanup?",
         "answer": "Give frequently used items a predictable home and use a short reset routine. If something repeatedly lands outside its zone, move the zone instead of adding more storage."},
        {"question": f"Should I buy containers before organizing {topic}?",
         "answer": "Usually no. Measure and test the layout first, then buy containers that fit the actual shelves, drawers, or floor area. This reduces wasted space and unnecessary purchases."},
    ]


def build_faq_messages(keyword, title):
    base_prompt = """
You are an editorial FAQ writer for a Home Organization website.

Create 4-6 useful FAQ questions and concise answers for one practical article.
Questions should reflect real reader intent and common search questions, without claiming access to proprietary search data.

Rules:
- Exactly 4-6 items.
- Every question must end with a question mark.
- Answers must be 40-110 words and directly answer the question.
- No hype, no keyword stuffing, no invented statistics.
- Do not repeat the article title as a question.

Return exactly:
{
  "faq": [
    {"question": "Question?", "answer": "Answer."}
  ]
}
""".strip()
    system_prompt = build_json_system_prompt(base_prompt)
    user_prompt = f"FOCUS KEYWORD:\n{keyword}\n\nARTICLE TITLE:\n{title}\n\nCreate the FAQ now."
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def validate_faq(result):
    if not isinstance(result, dict):
        raise ValueError("FAQ response must be a JSON object.")
    items = result.get("faq")
    if not isinstance(items, list):
        raise ValueError("FAQ response must contain a faq list.")

    cleaned = []
    seen = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not question or not answer or not question.endswith("?"):
            continue
        if len(answer.split()) < 40 or len(answer.split()) > 110:
            continue
        key = question.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"question": question, "answer": answer})

    if not FAQ_MIN_ITEMS <= len(cleaned) <= FAQ_MAX_ITEMS:
        raise ValueError(f"FAQ must contain {FAQ_MIN_ITEMS}-{FAQ_MAX_ITEMS} valid items; got {len(cleaned)}.")
    return cleaned


def generate_faq(api_key, keyword, title):
    messages = build_faq_messages(keyword, title)
    result, actual_model, layer = call_json_with_four_layers(
        api_key=api_key,
        messages=messages,
        temperature=0.4,
        max_tokens=1200,
        local_fallback_factory=lambda: {"faq": local_faq_fallback(keyword, title)},
        operation_name="FAQ",
    )
    try:
        faq = validate_faq(result)
    except Exception:
        faq = local_faq_fallback(keyword, title)
    print(f"FAQ model: {actual_model}")
    print(f"FAQ strategy: {layer}")
    print(f"FAQ items: {len(faq)}")
    return faq


def append_faq(content_markdown, faq):
    if not FAQ_MIN_ITEMS <= len(faq) <= FAQ_MAX_ITEMS:
        raise ValueError("append_faq received an invalid FAQ count.")
    parts = [content_markdown.strip(), "### Frequently Asked Questions"]
    for item in faq:
        parts.append(f"**{item['question'].strip()}**\n\n{item['answer'].strip()}")
    return "\n\n".join(parts).strip()


def clean_section_text(content):
    content = str(content).strip()

    content = re.sub(
        r"^```(?:markdown|md)?\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)
    content = re.sub(
        r"^\s*##[ \t]+[^\n]+\n+",
        "",
        content,
        count=1,
    )
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


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

    content = re.sub(
        r"(?mi)^[ \t]*Tags:"
        r"[ \t]*\[[^\r\n]*\]"
        r"[ \t]*\r?\n?",
        "",
        content,
    )

    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


def count_words(text):
    plain = re.sub(r"`[^`]+`", "", str(text))
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", plain)
    plain = re.sub(r"\[[^\]]*\]\([^)]*\)", "", plain)

    return len(
        re.findall(
            r"\b[\w'-]+\b",
            plain,
            flags=re.UNICODE,
        )
    )


def count_h2(content):
    return len(
        re.findall(
            r"^\s*##\s+\S+",
            str(content),
            re.MULTILINE,
        )
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
                fence_marker = (
                    "```"
                    if stripped.startswith("```")
                    else "~~~"
                )
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
                    sections.append({
                        "heading": current_heading,
                        "body": "\n".join(
                            current_body
                        ).strip(),
                    })

                current_heading = (
                    match.group(1).strip()
                )
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


def assemble_article(
    title, meta_description, tags,
    h2_headings, sections,
):
    if len(h2_headings) != REQUIRED_SECTION_COUNT:
        raise ValueError(
            "Assembly requires exactly 10 H2 headings."
        )

    if len(sections) != REQUIRED_SECTION_COUNT:
        raise ValueError(
            "Assembly requires exactly 10 sections."
        )

    parts = []

    for heading, section in zip(h2_headings, sections):
        if not section:
            raise ValueError(
                f"Missing section for H2: {heading}"
            )

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
            f"Assembly: expected "
            f"{REQUIRED_SECTION_COUNT} H2, "
            f"got {h2_count}."
        )

    if words < MIN_ACCEPTABLE_WORDS:
        raise ValueError(
            f"Assembly: {words} words below "
            f"minimum {MIN_ACCEPTABLE_WORDS}."
        )

    if words > MAX_WORDS:
        raise ValueError(
            f"Assembly: {words} words exceeds "
            f"maximum {MAX_WORDS}."
        )

    return (content_markdown, words, h2_count)


def shorten_title(title, keyword):
    title = str(title).strip()

    if len(title) <= MAX_TITLE_LENGTH:
        return title

    trimmed = title[:MAX_TITLE_LENGTH].rstrip()
    trimmed = re.sub(r"[\s:;\-,]+$", "", trimmed)

    if (
        keyword
        and keyword.lower() not in trimmed.lower()
    ):
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


def generate_image_queries(
    api_key, title, content_markdown,
):
    sections = extract_h2_sections(content_markdown)

    if len(sections) < 4:
        raise ValueError(
            "At least four H2 sections are required "
            "for image queries."
        )

    selected_sections = sections[:4]
    section_payload = []

    for index, section in enumerate(
        selected_sections, start=1,
    ):
        body = re.sub(
            r"\n{3,}", "\n\n", section["body"],
        ).strip()[:500]

        section_payload.append(
            f"SECTION {index}\n"
            f"H2: {section['heading']}\n"
            f"CONTENT: {body}\n"
        )

    sections_text = "\n".join(section_payload)

    base_prompt = """
You are a visual content editor for a Home Organization website.

Create exactly 5 highly relevant and visually distinct
Pexels queries.

QUERY 1: Hero image for the whole article.
QUERIES 2-5: One image query for each of the first four
H2 sections.

RULES:
- Exactly 5 unique queries.
- 5-14 words per query.
- Concrete visual nouns.
- No photographer names.
- No SEO keyword stuffing.
- No duplicate scenes.

The JSON object must contain exactly:
{
  "image_queries": [
    "query 1", "query 2", "query 3", "query 4", "query 5"
  ]
}
""".strip()

    system_prompt = build_json_system_prompt(base_prompt)

    user_prompt = (
        f"ARTICLE TITLE:\n{title}\n\n"
        f"{sections_text}\n\n"
        "Return exactly 5 unique queries."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    print("")
    print("=== IMAGE QUERIES ===")

    result, actual_model, layer = call_json_with_four_layers(
        api_key=api_key,
        messages=messages,
        temperature=0.4,
        max_tokens=IMAGE_QUERY_MAX_TOKENS,
        local_fallback_factory=lambda: {
            "image_queries": local_image_query_fallback(
                title, content_markdown,
            )
        },
        operation_name="IMAGE-QUERIES",
    )

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
            "Exactly 5 unique image queries required."
        )

    print(f"Image-query model: {actual_model}")
    print(f"Image-query strategy: {layer}")

    for index, query in enumerate(
        image_queries, start=1,
    ):
        label = (
            "HERO" if index == 1 else f"H2 #{index - 1}"
        )
        print(f"  {index}. [{label}] {query}")

    return image_queries


def generate_article_pipeline(
    api_key, keyword, specific_angle,
):
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
        keyword=keyword,
    )

    (
        content_markdown,
        word_count,
        h2_count,
    ) = assemble_article(
        title=title,
        meta_description=meta_description,
        tags=tags,
        h2_headings=h2_headings,
        sections=sections,
    )

    faq = generate_faq(api_key=api_key, keyword=keyword, title=title)
    content_markdown = append_faq(content_markdown, faq)

    # CRITICAL: keyword must appear in the assembled content
    if keyword.lower() not in content_markdown.lower():
        first_h2_match = re.search(
            r"^(##[^\n]+\n\n)",
            content_markdown,
            re.MULTILINE,
        )

        if first_h2_match:
            insertion_point = first_h2_match.end()
            injection = (
                f"These {keyword} strategies are designed "
                f"for real homes with limited space. "
            )
            content_markdown = (
                content_markdown[:insertion_point]
                + injection
                + content_markdown[insertion_point:]
            )
            print("Keyword injected into content.")

    title = shorten_title(title, keyword)
    meta_description = shorten_meta(meta_description)

    if keyword.lower() not in title.lower():
        raise ValueError(
            "Final title missing focus keyword."
        )

    final_word_count = count_words(content_markdown)
    final_h2_count = count_h2(content_markdown)

    if final_word_count < MIN_ACCEPTABLE_WORDS:
        raise ValueError(
            f"Final article too short: "
            f"{final_word_count} words."
        )

    if final_h2_count != REQUIRED_SECTION_COUNT:
        raise ValueError(
            f"Final article must contain exactly "
            f"{REQUIRED_SECTION_COUNT} H2; "
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


def save_article(article):
    temp_path = ARTICLE_PATH.with_suffix(".json.tmp")

    with temp_path.open(
        "w", encoding="utf-8", newline="\n",
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
            "ERROR: GROQ_API_KEY is missing.",
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

    print("")
    print("================================================")
    print("AUTO BLOG - SECTIONED ARTICLE GENERATION")
    print("================================================")
    print(f"Keyword: {keyword}")
    print(f"Primary model: {GROQ_MODEL}")
    print(f"Fallback model: {FALLBACK_GROQ_MODEL}")

    try:
        mark_keyword_processing(
            keyword, rows, fieldnames,
            keyword_col, status_col,
        )
        print("Keyword status: processing")
    except Exception as exc:
        print(
            f"ERROR changing keyword status: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        specific_angle = pick_specific_angle(
            api_key, keyword,
        )
        print(f"Specific angle: {specific_angle}")

        pipeline_result = None
        last_pipeline_error = None

        for pipeline_attempt in range(
            1, MAX_PIPELINE_ATTEMPTS + 1,
        ):
            print("")
            print(
                "================================================"
            )
            print(
                f"PIPELINE ATTEMPT "
                f"{pipeline_attempt}/"
                f"{MAX_PIPELINE_ATTEMPTS}"
            )
            print(
                "================================================"
            )

            try:
                pipeline_result = (
                    generate_article_pipeline(
                        api_key=api_key,
                        keyword=keyword,
                        specific_angle=specific_angle,
                    )
                )
                print(
                    f"Pipeline attempt "
                    f"{pipeline_attempt} succeeded."
                )
                break

            except Exception as exc:
                last_pipeline_error = exc
                print(
                    f"Pipeline attempt "
                    f"{pipeline_attempt} failed: {exc}",
                    file=sys.stderr,
                )

                if (
                    pipeline_attempt
                    < MAX_PIPELINE_ATTEMPTS
                ):
                    print(
                        "Restarting pipeline from "
                        "Phase 1..."
                    )
                    time.sleep(3)

        if pipeline_result is None:
            raise RuntimeError(
                f"All pipeline attempts failed. "
                f"Last error: {last_pipeline_error}"
            )

        title = pipeline_result["title"]
        meta_description = (
            pipeline_result["meta_description"]
        )
        tags = pipeline_result["tags"]
        content_markdown = (
            pipeline_result["content_markdown"]
        )
        h2_headings = pipeline_result["h2_headings"]
        faq = pipeline_result["faq"]

        image_queries = generate_image_queries(
            api_key=api_key,
            title=title,
            content_markdown=content_markdown,
        )

        if len(image_queries) != 5:
            raise ValueError(
                "Image-query generation did not "
                "return exactly 5 queries."
            )

        slug = slugify(title)

        if not slug:
            raise ValueError(
                "Could not generate a valid slug."
            )

        final_word_count = count_words(
            content_markdown
        )
        final_h2_count = count_h2(content_markdown)

        if final_word_count < MIN_WORDS:
            print(
                f"WARNING: below preferred "
                f"{MIN_WORDS}-word target: "
                f"{final_word_count} words."
            )

        if final_word_count < MIN_ACCEPTABLE_WORDS:
            raise ValueError(
                f"Final article below hard minimum "
                f"of {MIN_ACCEPTABLE_WORDS} words."
            )

        if final_word_count > MAX_WORDS:
            raise ValueError(
                f"Final article exceeds "
                f"{MAX_WORDS} words."
            )

        if final_h2_count != REQUIRED_SECTION_COUNT:
            raise ValueError(
                f"Final article must have exactly "
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
            "faq": faq,
            "word_count": final_word_count,
            "h2_count": final_h2_count,
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        save_article(article)

        print("")
        print(
            "================================================"
        )
        print("ARTICLE GENERATED SUCCESSFULLY")
        print(
            "================================================"
        )
        print(f"Keyword: {keyword}")
        print(f"Title: {title}")
        print(f"Slug: {slug}")
        print(f"Words: {final_word_count}")
        print(f"H2: {final_h2_count}")
        print(f"Title length: {len(title)}")
        print(
            f"Meta length: {len(meta_description)}"
        )
        print(f"Tags: {', '.join(tags)}")
        print(f"Saved: {ARTICLE_PATH}")

        return 0

    except Exception as exc:
        print("")
        print(
            "================================================",
            file=sys.stderr,
        )
        print(
            "ARTICLE GENERATION FAILED",
            file=sys.stderr,
        )
        print(
            "================================================",
            file=sys.stderr,
        )
        print(f"Error: {exc}", file=sys.stderr)

        try:
            mark_keyword_pending(keyword)
            print(
                f"Keyword returned to pending: "
                f"{keyword}"
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
