#!/usr/bin/env python3

import json
import os
import re
import sys
import time

from pathlib import Path
from typing import Any, Dict, List, Optional

from groq import Groq


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTICLE_PATH = ROOT_DIR / "article.json"

IMAGE_COUNT = 10
MAX_RETRIES = 5

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)

FALLBACK_GROQ_MODEL = "llama-3.1-8b-instant"

ROOM_TERMS = {
    "bathroom",
    "bedroom",
    "kitchen",
    "pantry",
    "closet",
    "entryway",
    "hallway",
    "foyer",
    "living room",
    "home office",
    "office",
    "laundry room",
    "garage",
    "nursery",
    "dining room",
    "apartment",
    "studio",
    "small space",
}

VISUAL_OBJECT_TERMS = {
    "cabinet",
    "drawer",
    "shelf",
    "shelves",
    "bin",
    "bins",
    "basket",
    "baskets",
    "rack",
    "rod",
    "hooks",
    "hook",
    "tray",
    "container",
    "containers",
    "organizer",
    "organizers",
    "shelving",
    "vanity",
    "sink",
    "counter",
    "countertop",
    "closet",
    "wardrobe",
    "dresser",
    "shoe rack",
    "pegboard",
    "cart",
    "trolley",
    "bench",
}

STORAGE_TERMS = {
    "storage",
    "organization",
    "organizing",
    "organized",
    "decluttering",
    "space saving",
    "pull out",
    "pull-out",
    "vertical storage",
    "hidden storage",
    "under sink",
    "under-sink",
    "drawer storage",
    "cabinet storage",
    "wall storage",
    "door storage",
    "stacked storage",
}


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
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def extract_json_from_response(
    response_text: str,
) -> Dict[str, Any]:
    if not isinstance(response_text, str):
        raise ValueError(
            "Groq response is not a string."
        )

    text = response_text.strip()

    if not text:
        raise ValueError(
            "Groq returned an empty response."
        )

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
        result = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise ValueError(
                "Groq response does not contain "
                "a valid JSON object."
            )

        try:
            result = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Groq returned invalid JSON: {exc}"
            ) from exc

    if not isinstance(result, dict):
        raise ValueError(
            "Groq response must be a JSON object."
        )

    return result


def extract_sections(
    content: str,
) -> List[Dict[str, str]]:
    sections: List[Dict[str, str]] = []

    current_heading: Optional[str] = None
    current_lines: List[str] = []

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
                and stripped.startswith(fence_marker)
            ):
                in_fenced_code_block = False
                fence_marker = None

            if current_heading is not None:
                current_lines.append(line)

            continue

        if in_fenced_code_block:
            if current_heading is not None:
                current_lines.append(line)

            continue

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
                            current_lines
                        ).strip(),
                    }
                )

            current_heading = clean_text(
                match.group(1)
            )
            current_lines = []
            continue

        if current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections.append(
            {
                "heading": current_heading,
                "body": "\n".join(
                    current_lines
                ).strip(),
            }
        )

    return sections


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
        r"^#{1,6}[ \t]+",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"[*_~>]+",
        " ",
        text,
    )
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def extract_first_two_paragraphs(
    body: str,
) -> List[str]:
    plain = remove_markdown(body)

    raw_parts = re.split(
        r"\n\s*\n",
        body,
    )

    paragraphs: List[str] = []

    for part in raw_parts:
        cleaned = remove_markdown(part)

        if len(cleaned) < 35:
            continue

        if cleaned.startswith("- "):
            continue

        if re.match(r"^\d+\.\s+", cleaned):
            continue

        paragraphs.append(cleaned)

        if len(paragraphs) >= 2:
            break

    if not paragraphs and plain:
        paragraphs = [plain[:600]]

    return paragraphs[:2]


def extract_visual_nouns(
    text: str,
) -> List[str]:
    normalized = text.lower()

    terms: List[str] = []

    all_terms = (
        ROOM_TERMS
        | VISUAL_OBJECT_TERMS
        | STORAGE_TERMS
    )

    for term in sorted(
        all_terms,
        key=len,
        reverse=True,
    ):
        if term.lower() in normalized:
            if term not in terms:
                terms.append(term)

    words = re.findall(
        r"\b[a-z][a-z-]{3,}\b",
        normalized,
    )

    stop_words = {
        "about",
        "after",
        "again",
        "also",
        "because",
        "before",
        "being",
        "between",
        "could",
        "every",
        "first",
        "from",
        "have",
        "into",
        "more",
        "other",
        "should",
        "their",
        "these",
        "those",
        "through",
        "using",
        "where",
        "which",
        "while",
        "would",
        "your",
    }

    for word in words:
        if word in stop_words:
            continue

        if word in terms:
            continue

        if (
            word.endswith("ing")
            and word not in {
                "organizing",
                "decluttering",
            }
        ):
            continue

        if word not in terms:
            terms.append(word)

        if len(terms) >= 14:
            break

    return terms[:14]


def build_section_payload(
    sections: List[Dict[str, str]],
) -> str:
    payload = []

    for index, section in enumerate(
        sections,
        start=1,
    ):
        paragraphs = extract_first_two_paragraphs(
            section["body"]
        )

        context = " ".join(paragraphs)

        nouns = extract_visual_nouns(
            " ".join(
                [
                    section["heading"],
                    context,
                ]
            )
        )

        payload.append(
            "\n".join(
                [
                    f"SECTION {index}",
                    f"H2: {section['heading']}",
                    "FIRST TWO PARAGRAPHS:",
                    context,
                    "VISUAL NOUNS:",
                    ", ".join(nouns),
                ]
            )
        )

    return "\n\n".join(payload)


def normalize_query(query: str) -> str:
    query = clean_text(query)

    query = query.replace("&", "and")

    query = re.sub(
        r"[^A-Za-z0-9,\- ]+",
        " ",
        query,
    )

    query = re.sub(
        r"\s+",
        " ",
        query,
    )

    return query.strip()


def validate_query_shape(query: str) -> bool:
    words = query.split()

    if len(words) < 4:
        return False

    if len(words) > 14:
        return False

    return True


def make_unique(queries: List[str]) -> List[str]:
    result = []
    seen = set()

    for query in queries:
        query = normalize_query(query)

        if not query:
            continue

        key = query.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(query)

    return result


def get_status_code(exception: Exception) -> Optional[int]:
    response = getattr(
        exception,
        "response",
        None,
    )

    if response is not None:
        status_code = getattr(
            response,
            "status_code",
            None,
        )

        if status_code is not None:
            return status_code

    return getattr(
        exception,
        "status_code",
        None,
    )


def build_prompts(
    article: Dict[str, Any],
    sections: List[Dict[str, str]],
) -> tuple:
    title = clean_text(article.get("title", ""))
    keyword = clean_text(article.get("keyword", ""))

    section_payload = build_section_payload(sections)

    system_prompt = """
You are a professional visual content editor for an
English-language Home Organization & Small-Space Living website.

Create exactly 10 highly specific Pexels search queries from
the FINAL article after editorial content upgrading.

The article has already been written. Do not infer image topics
from headings alone.

QUERY STRUCTURE:
Every query should follow this conceptual structure:

[room/context] + [specific object] +
[specific storage solution] + [visual scene]

Examples:
- bathroom under sink pull out cabinet storage bins
- bedroom under bed rolling storage containers organized
- kitchen pantry cabinet tiered shelf spice storage

BAD:
- Planning Pull-Out Bin System home interior
- bathroom organization interior
- modern home storage
- organized home

For every section query:
1. Read the H2.
2. Read the first two paragraphs.
3. Identify the concrete objects and storage technique.
4. Identify the room or physical context.
5. Describe a realistic photographable scene.
6. Use concrete nouns rather than abstract SEO language.

IMAGE PLAN:
- Query 1 is the HERO.
- Queries 2-10 correspond to the first 9 useful H2
  sections in order.
- If there are fewer than 9 H2 sections, use the remaining
  strongest sections without duplicating a query.
- If there are more than 9 H2 sections, use the first 9
  substantive sections.
- Never create a query from an H2 heading alone.

HERO:
- Wide editorial room scene.
- Represents the overall article topic.
- Must contain enough context to understand the room.
- Avoid close-up single objects.

SECTION IMAGES:
- Specific to the section.
- Show the actual storage object or technique.
- Prefer realistic homes over abstract product photography.
- Do not use generic "organized home" scenes when a concrete
  object is available.

STYLE:
- concise English
- 5-14 words
- no quotation marks
- no photographer names
- no camera instructions
- no SEO commentary
- no article title inside queries
- no H2 labels inside queries
- no duplicate queries
- no generic filler words such as "beautiful", "amazing",
  "best", or "perfect"

Return ONLY valid JSON:

{
  "image_queries": [
    "hero query",
    "section query 1",
    "section query 2",
    "section query 3",
    "section query 4",
    "section query 5",
    "section query 6",
    "section query 7",
    "section query 8",
    "section query 9"
  ]
}
""".strip()

    user_prompt = f"""
ARTICLE TITLE:
{title}

FOCUS KEYWORD:
{keyword}

FINAL ARTICLE SECTIONS:
{section_payload}

Generate exactly 10 Pexels queries.

Query 1:
A wide hero scene representing the whole article.

Queries 2-10:
One query for each of the first nine substantive sections.

Every query must be based on actual visual information in the
section content. Use concrete objects, rooms, storage systems,
and photographable scenes.

Return only the JSON object.
""".strip()

    return system_prompt, user_prompt


def generate_queries(
    api_key: str,
    article: Dict[str, Any],
    sections: List[Dict[str, str]],
) -> List[str]:
    client = Groq(api_key=api_key)

    system_prompt, user_prompt = build_prompts(
        article,
        sections,
    )

    retryable_codes = {
        429,
        500,
        502,
        503,
        504,
    }

    def call_model(model: str) -> List[str]:
        last_exception: Optional[Exception] = None

        for attempt in range(
            1,
            MAX_RETRIES + 1,
        ):
            try:
                print(
                    "Generating final-content image plan "
                    f"with model={model} "
                    f"(attempt {attempt}/{MAX_RETRIES})..."
                )

                response = client.chat.completions.create(
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
                    temperature=0.35,
                    max_tokens=1800,
                    response_format={
                        "type": "json_object"
                    },
                )

                if not response.choices:
                    raise ValueError(
                        "Groq returned no choices."
                    )

                content = getattr(
                    response.choices[0].message,
                    "content",
                    None,
                )

                result = extract_json_from_response(
                    content or ""
                )

                raw_queries = result.get(
                    "image_queries"
                )

                if not isinstance(raw_queries, list):
                    raise ValueError(
                        "'image_queries' must be a list."
                    )

                queries = []

                for query in raw_queries:
                    if not isinstance(query, str):
                        continue

                    query = normalize_query(query)

                    if not validate_query_shape(query):
                        continue

                    lower_existing = {
                        item.lower()
                        for item in queries
                    }

                    if query.lower() not in lower_existing:
                        queries.append(query)

                if len(queries) != IMAGE_COUNT:
                    raise ValueError(
                        "Groq must return exactly "
                        f"{IMAGE_COUNT} valid unique "
                        "image queries."
                    )

                print(
                    f"Groq image planning succeeded "
                    f"with model={model}."
                )

                return queries

            except Exception as exc:
                last_exception = exc
                status_code = get_status_code(exc)

                print(
                    f"Image planning failed "
                    f"(model={model}, "
                    f"attempt={attempt}/{MAX_RETRIES}, "
                    f"status={status_code}): {exc}",
                    file=sys.stderr,
                )

                if status_code is not None:
                    if status_code not in retryable_codes:
                        raise

                if attempt >= MAX_RETRIES:
                    break

                delay = min(
                    2 ** (attempt - 1),
                    30,
                )

                print(
                    f"Retrying model={model} "
                    f"in {delay} seconds..."
                )

                time.sleep(delay)

        raise RuntimeError(
            "Groq image planning failed after "
            f"{MAX_RETRIES} attempts using "
            f"model '{model}': "
            f"{last_exception}"
        ) from last_exception

    # ---------------------------------------------------------
    # PRIMARY MODEL
    # ---------------------------------------------------------
    try:
        return call_model(GROQ_MODEL)

    except Exception as primary_exc:
        primary_status = get_status_code(
            primary_exc
        )

        if primary_status != 429:
            raise

        print(
            "Primary model failed with 429."
        )
        print(
            "Switching to fallback model: "
            f"{FALLBACK_GROQ_MODEL}"
        )

    # ---------------------------------------------------------
    # FALLBACK MODEL
    # ---------------------------------------------------------
    try:
        return call_model(FALLBACK_GROQ_MODEL)

    except Exception as fallback_exc:
        print(
            "Groq fallback failed.",
            file=sys.stderr,
        )
        print(
            f"  Model: {FALLBACK_GROQ_MODEL}",
            file=sys.stderr,
        )
        print(
            f"  Status code: "
            f"{get_status_code(fallback_exc)}",
            file=sys.stderr,
        )
        print(
            f"  Reason: {fallback_exc}",
            file=sys.stderr,
        )

        raise


def build_local_fallback_queries(
    article: Dict[str, Any],
    sections: List[Dict[str, str]],
) -> List[str]:
    keyword = clean_text(
        article.get("keyword", "")
    ).lower()

    candidates = []

    for section in sections:
        body = " ".join(
            extract_first_two_paragraphs(
                section["body"]
            )
        )

        source = " ".join(
            [
                section["heading"],
                body,
            ]
        )

        source_lower = source.lower()

        rooms = [
            term
            for term in ROOM_TERMS
            if term in source_lower
        ]

        objects = [
            term
            for term in VISUAL_OBJECT_TERMS
            if term in source_lower
        ]

        storage = [
            term
            for term in STORAGE_TERMS
            if term in source_lower
        ]

        room = rooms[0] if rooms else keyword

        obj = (
            objects[0]
            if objects
            else "storage cabinet"
        )

        solution = (
            storage[0]
            if storage
            else "organized storage"
        )

        candidates.append(
            normalize_query(
                f"{room} {obj} "
                f"{solution} organized interior"
            )
        )

    candidates.insert(
        0,
        normalize_query(
            f"{keyword} organized home "
            f"storage interior wide shot"
        ),
    )

    candidates = make_unique(candidates)

    generic_fallbacks = [
        "bathroom cabinet storage organized interior",
        "bedroom closet storage bins organized interior",
        "kitchen cabinet storage containers organized",
        "small apartment storage furniture organized",
        "entryway storage cabinet organized interior",
        "home office drawer storage organized workspace",
        "laundry room cabinet storage organized interior",
        "under sink cabinet storage organized bathroom",
        "small space vertical storage organized room",
    ]

    candidates = make_unique(
        candidates + generic_fallbacks
    )

    if len(candidates) < IMAGE_COUNT:
        raise ValueError(
            "Could not build 10 unique fallback queries."
        )

    return candidates[:IMAGE_COUNT]


def main() -> int:
    print("=" * 70)
    print("COMPETITIVE IMAGE PLAN")
    print("=" * 70)

    try:
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set."
            )

        article = load_article()

        title = clean_text(
            article.get("title", "")
        )

        keyword = clean_text(
            article.get("keyword", "")
        )

        content = article.get("content_markdown", "")

        if not title:
            raise ValueError(
                "article.json is missing 'title'."
            )

        if not keyword:
            raise ValueError(
                "article.json is missing 'keyword'."
            )

        if (
            not isinstance(content, str)
            or not content.strip()
        ):
            raise ValueError(
                "article.json is missing valid "
                "'content_markdown'."
            )

        sections = extract_sections(content)

        if len(sections) < 4:
            raise ValueError(
                "The final article contains fewer "
                "than 4 H2 sections."
            )

        print(f"Article title: {title}")
        print(f"Focus keyword: {keyword}")
        print(f"Final H2 sections: {len(sections)}")

        for index, section in enumerate(
            sections,
            start=1,
        ):
            paragraphs = extract_first_two_paragraphs(
                section["body"]
            )

            print(
                f"  H2 #{index}: {section['heading']}"
            )

            if paragraphs:
                print(
                    "    Visual context: "
                    + paragraphs[0][:180]
                )

        try:
            queries = generate_queries(
                api_key,
                article,
                sections,
            )
        except Exception as groq_exc:
            print(
                "WARNING: Groq image planning failed.",
                file=sys.stderr,
            )
            print(
                f"Reason: {groq_exc}",
                file=sys.stderr,
            )
            print(
                "Using content-derived local fallback."
            )

            queries = build_local_fallback_queries(
                article,
                sections,
            )

        queries = make_unique(queries)

        if len(queries) != IMAGE_COUNT:
            raise ValueError(
                "Exactly 10 unique image queries "
                "are required."
            )

        article["image_queries"] = queries

        save_article(article)

        print("")
        print("FINAL IMAGE QUERIES:")

        for index, query in enumerate(
            queries,
            start=1,
        ):
            if index == 1:
                label = "HERO"
            else:
                label = f"IMAGE {index}"

            print(
                f"{index:02d}. [{label}] {query}"
            )

        print("")
        print(
            f"Saved {len(queries)} queries "
            f"to {ARTICLE_PATH}"
        )
        print("=" * 70)
        print(
            "COMPETITIVE IMAGE PLAN COMPLETE"
        )
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print(
            "Operation cancelled.",
            file=sys.stderr,
        )
        return 130

    except Exception as exc:
        print("", file=sys.stderr)
        print(
            "COMPETITIVE IMAGE PLAN FAILED",
            file=sys.stderr,
        )
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
