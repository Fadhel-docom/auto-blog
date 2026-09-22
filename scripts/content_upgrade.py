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

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)

MAX_RETRIES = 5

MIN_WORDS = 1500
MAX_WORDS = 2400

MIN_H2 = 10
MAX_H2 = 11


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

    except OSError as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        raise RuntimeError(
            f"Could not save article.json: {exc}"
        ) from exc


def get_required_string(
    article: Dict[str, Any],
    field_name: str,
) -> str:
    value = article.get(field_name)

    if not isinstance(value, str):
        raise ValueError(
            f"article.json field '{field_name}' must be a string."
        )

    value = value.strip()

    if not value:
        raise ValueError(
            f"article.json field '{field_name}' is empty."
        )

    return value


def count_words(text: str) -> int:
    if not isinstance(text, str):
        return 0

    plain = re.sub(r"`[^`]+`", " ", text)
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", plain)
    plain = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", plain)
    plain = re.sub(r"[#>*_~`]+", " ", plain)

    words = re.findall(
        r"\b[\w'-]+\b",
        plain,
        flags=re.UNICODE,
    )

    return len(words)


def extract_h2_headings(content: str) -> List[str]:
    if not isinstance(content, str):
        return []

    headings = []

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

            continue

        if in_fenced_code_block:
            continue

        match = re.match(
            r"^\s*##[ \t]+([^#].*?)\s*$",
            line,
        )

        if match:
            heading = match.group(1).strip()

            if heading:
                headings.append(heading)

    return headings


def is_article_sufficient(content: str) -> bool:
    words = count_words(content)
    h2_count = len(extract_h2_headings(content))

    return (
        MIN_WORDS <= words <= MAX_WORDS
        and
        MIN_H2 <= h2_count <= MAX_H2
    )


def get_status_code(exception: Exception) -> Optional[int]:
    response = getattr(exception, "response", None)

    if response is not None:
        status_code = getattr(
            response,
            "status_code",
            None,
        )

        if status_code is not None:
            return status_code

    status_code = getattr(
        exception,
        "status_code",
        None,
    )

    return status_code


def clean_markdown(content: str) -> str:
    if not isinstance(content, str):
        raise ValueError(
            "Generated content must be a string."
        )

    content = content.strip()

    if not content:
        raise ValueError(
            "Generated content is empty."
        )

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

        if (
            start == -1
            or end == -1
            or end <= start
        ):
            raise ValueError(
                "Groq response does not contain "
                "a valid JSON object."
            )

        json_text = text[start:end + 1]

        try:
            result = json.loads(json_text)

        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Groq returned invalid JSON: {exc}"
            ) from exc

    if not isinstance(result, dict):
        raise ValueError(
            "Groq response must be a JSON object."
        )

    return result


def build_system_prompt() -> str:
    return """
You are an expert long-form SEO editor and writer
for an English-language website focused on:

Home Organization & Small-Space Living.

Your task is to improve an existing article.

The article already has a valid topic, keyword, title,
metadata, and general direction.

You must preserve the original topic and intent while
substantially improving the article's usefulness,
depth, organization, and readability.

LENGTH REQUIREMENT:
- The final article must contain between 1500 and 2400
  actual words.
- Aim for approximately 2000 words.
- You MUST produce at least 1800 words.
- If you finish before 1800 words, continue writing more
  detailed sections.
- Do NOT summarize.
- Do NOT stop early.
- Do NOT exceed 2400 words.

H2 REQUIREMENT:
- The final article must contain AT LEAST 10 H2 headings.
- Aim for EXACTLY 10 H2 headings.
- You may use 11 H2 headings only if strictly needed.
- Do NOT use fewer than 10 H2 headings.
- Do NOT use more than 11 H2 headings.
- Every H2 must contain useful, distinct information.
- Do not create empty or extremely short H2 sections.
- Do not use an H1 inside content_markdown.

ARTICLE STRUCTURE:
- Begin with a concise introduction.
- The introduction should naturally contain the exact
  focus keyword.
- Use 10 useful H2 sections (11 maximum).
- Use H3 headings only when they genuinely improve
  organization.
- End with a practical conclusion.
- Include a natural reader-focused CTA when appropriate.

HEADING RULES:
- H2 headings must use Markdown format:
  ## Heading
- H3 headings must use Markdown format:
  ### Heading
- Use only ASCII characters in H2 and H3 headings.
- Use A-Z, a-z, 0-9, spaces, and regular hyphens.
- Never use an em dash.
- Never use an en dash.
- Never use a non-breaking hyphen.
- Replace "&" with "and" in headings.
- Do not use parentheses in headings.
- Do not use brackets in headings.
- Avoid unusual punctuation in headings.
- Keep headings concise and descriptive.

CONTENT QUALITY:
- Make the article more useful than the original.
- Add concrete practical details.
- Add realistic examples.
- Add useful measurements when appropriate.
- Explain how and why a recommendation works.
- Include common mistakes and trade-offs when relevant.
- Avoid repetitive advice.
- Avoid filler paragraphs.
- Avoid generic motivational language.
- Use short paragraphs of approximately 2-4 sentences.
- Use numbered lists for processes.
- Use bullet lists when they improve scanability.
- Use bold sparingly for important ideas.

ACCURACY:
- Do not invent statistics.
- Do not invent studies.
- Do not invent expert quotes.
- Do not invent citations.
- Do not claim a specific product brand is recommended
  unless that brand already appears in the original article
  and the claim can be supported by the supplied text.
- Do not invent prices, reviews, certifications,
  measurements, or performance guarantees.
- If a measurement is presented as an example rather than
  a universal standard, make that distinction clear.

SEO:
- Preserve the exact focus keyword naturally.
- Keep the keyword in the title if it is already there.
- Ensure the exact focus keyword appears naturally
  in the introduction.
- Do not keyword-stuff.
- Preserve the article's search intent.
- Improve semantic coverage with closely related terms
  where natural.
- Do not add an artificial keyword list to the article.

IMAGES:
- Do not generate image queries.
- Do not generate image Markdown.
- Do not modify image metadata.
- Image planning happens in a separate pipeline step.

IMPORTANT:
The input article may already contain useful sections.
Do not blindly replace useful information with generic text.
Retain valuable concrete details while improving structure,
depth, transitions, and completeness.

OUTPUT:
Return ONLY valid JSON.

Use exactly this structure:

{
  "title": "article title",
  "meta_description": "meta description",
  "content_markdown": "complete improved article",
  "tags": ["tag 1", "tag 2"]
}

Do not wrap the JSON in Markdown code fences.
""".strip()


def build_user_prompt(article: Dict[str, Any]) -> str:
    keyword = str(article.get("keyword", "")).strip()
    specific_angle = str(article.get("specific_angle", "")).strip()
    title = str(article.get("title", "")).strip()
    meta_description = str(article.get("meta_description", "")).strip()
    content = str(article.get("content_markdown", "")).strip()
    tags = article.get("tags", [])

    if not isinstance(tags, list):
        tags = []

    clean_tags = []

    for tag in tags:
        if isinstance(tag, str):
            tag = tag.strip()

            if tag and tag not in clean_tags:
                clean_tags.append(tag)

    return f"""
Improve the following existing article.

FOCUS KEYWORD:
{keyword}

SPECIFIC ARTICLE ANGLE:
{specific_angle}

CURRENT TITLE:
{title}

CURRENT META DESCRIPTION:
{meta_description}

CURRENT TAGS:
{", ".join(clean_tags)}

CURRENT ARTICLE:

{content}

EDITORIAL TASK:

Rewrite and improve this article while preserving
its original search intent and specific topic.

The final version must:

1. Contain between 1500 and 2400 actual words.
2. Aim for approximately 2000 words.
3. You MUST produce at least 1800 words.
4. If you finish before 1800 words, continue writing
   more detailed sections.
5. Do NOT summarize.
6. Contain AT LEAST 10 H2 headings.
7. Aim for EXACTLY 10 H2 headings.
8. Do NOT use fewer than 10 H2 headings.
9. Do NOT use more than 11 H2 headings.
10. Keep the exact focus keyword naturally in the title
    and introduction.
11. Preserve useful concrete information from the original.
12. Add depth where the original is too short or shallow.
13. Remove repetitive or low-value passages.
14. Improve transitions between sections.
15. Make every H2 section materially useful.
16. Avoid invented facts, statistics, studies, citations,
    quotes, prices, or unsupported claims.
17. Do not create image queries.
18. Do not create image Markdown.
19. Do not mention this editing process.
20. Do not mention AI.

Return ONLY the JSON object requested by the system prompt.
""".strip()


def generate_upgrade(
    api_key: str,
    article: Dict[str, Any],
) -> Dict[str, Any]:
    client = Groq(api_key=api_key)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(article)

    last_exception: Optional[Exception] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(
                "Calling Groq for content upgrade "
                f"(attempt {attempt}/{MAX_RETRIES})..."
            )

            response = client.chat.completions.create(
                model=GROQ_MODEL,
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
                temperature=0.6,
                max_tokens=16000,
                response_format={
                    "type": "json_object"
                },
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

            return generated

        except Exception as exc:
            last_exception = exc
            status_code = get_status_code(exc)

            retryable_codes = {
                429,
                500,
                502,
                503,
                504,
            }

            if (
                status_code is not None
                and status_code not in retryable_codes
            ):
                break

            if attempt >= MAX_RETRIES:
                break

            delay = min(2 ** (attempt - 1), 30)

            print(
                f"Groq content upgrade failed: {exc}",
                file=sys.stderr,
            )

            print(
                f"Retrying in {delay} seconds..."
            )

            time.sleep(delay)

    raise RuntimeError(
        "Groq content upgrade failed after "
        f"{MAX_RETRIES} attempts: {last_exception}"
    )


def normalize_tags(raw_tags: Any) -> List[str]:
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]

    if not isinstance(raw_tags, list):
        return []

    tags = []

    for tag in raw_tags:
        if not isinstance(tag, str):
            continue

        tag = tag.strip()

        if tag and tag not in tags:
            tags.append(tag)

    return tags


def validate_generated_article(
    original_article: Dict[str, Any],
    generated: Dict[str, Any],
) -> Dict[str, Any]:
    original_title = str(
        original_article.get("title", "")
    ).strip()

    original_meta = str(
        original_article.get("meta_description", "")
    ).strip()

    original_tags = normalize_tags(
        original_article.get("tags", [])
    )

    title = generated.get("title")
    meta_description = generated.get("meta_description")
    content_markdown = generated.get("content_markdown")

    if not isinstance(title, str):
        raise ValueError(
            "Groq output field 'title' must be a string."
        )

    if not isinstance(meta_description, str):
        raise ValueError(
            "Groq output field 'meta_description' "
            "must be a string."
        )

    if not isinstance(content_markdown, str):
        raise ValueError(
            "Groq output field 'content_markdown' "
            "must be a string."
        )

    title = title.strip()
    meta_description = meta_description.strip()
    content_markdown = clean_markdown(content_markdown)

    if not title:
        raise ValueError(
            "Groq generated an empty title."
        )

    if not meta_description:
        raise ValueError(
            "Groq generated an empty meta description."
        )

    if not content_markdown:
        raise ValueError(
            "Groq generated empty content."
        )

    keyword = str(
        original_article.get("keyword", "")
    ).strip()

    if keyword:
        if keyword.lower() not in title.lower():
            raise ValueError(
                "The upgraded title does not contain "
                "the exact focus keyword."
            )

        introduction = content_markdown[:1800].lower()

        if keyword.lower() not in introduction:
            raise ValueError(
                "The upgraded introduction does not "
                "contain the exact focus keyword."
            )

    words = count_words(content_markdown)
    h2_headings = extract_h2_headings(content_markdown)
    h2_count = len(h2_headings)

    print(f"Generated word count: {words}")
    print(f"Generated H2 count: {h2_count}")

    if words < MIN_WORDS:
        raise ValueError(
            "Generated article is too short: "
            f"{words} words. Minimum is {MIN_WORDS}."
        )

    if words > MAX_WORDS:
        raise ValueError(
            "Generated article is too long: "
            f"{words} words. Maximum is {MAX_WORDS}."
        )

    if h2_count < MIN_H2:
        raise ValueError(
            "Generated article has too few H2 "
            f"headings: {h2_count}. Minimum is {MIN_H2}."
        )

    if h2_count > MAX_H2:
        raise ValueError(
            "Generated article has too many H2 "
            f"headings: {h2_count}. Maximum is {MAX_H2}."
        )

    tags = normalize_tags(generated.get("tags"))

    if not tags:
        tags = original_tags

    if not tags:
        raise ValueError(
            "No valid tags are available."
        )

    if not title:
        title = original_title

    if not meta_description:
        meta_description = original_meta

    return {
        "title": title,
        "meta_description": meta_description,
        "content_markdown": content_markdown,
        "tags": tags,
        "word_count": words,
    }


def build_updated_article(
    original_article: Dict[str, Any],
    validated: Dict[str, Any],
) -> Dict[str, Any]:
    updated_article = dict(original_article)

    updated_article["title"] = validated["title"]
    updated_article["meta_description"] = validated["meta_description"]
    updated_article["content_markdown"] = validated["content_markdown"]
    updated_article["tags"] = validated["tags"]
    updated_article["word_count"] = validated["word_count"]

    return updated_article


def print_article_stats(label: str, content: str) -> None:
    words = count_words(content)
    headings = extract_h2_headings(content)

    print("")
    print(f"{label} article statistics:")
    print(f"  Words: {words}")
    print(f"  H2 headings: {len(headings)}")

    if headings:
        print("  H2 structure:")

        for index, heading in enumerate(headings, start=1):
            print(f"    {index}. {heading}")

    print("")


def main() -> int:
    print("=" * 70)
    print("CONTENT UPGRADE")
    print("=" * 70)

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        print(
            "ERROR: GROQ_API_KEY is not set.",
            file=sys.stderr,
        )

        return 1

    try:
        article = load_article()

        content = get_required_string(
            article,
            "content_markdown",
        )

        keyword = str(article.get("keyword", "")).strip()
        title = str(article.get("title", "")).strip()

        print(f"Focus keyword: {keyword}")
        print(f"Current title: {title}")

        print_article_stats("Current", content)

        current_words = count_words(content)
        current_h2 = len(extract_h2_headings(content))

        print("Target:")
        print(f"  Words: {MIN_WORDS}-{MAX_WORDS}")
        print(f"  H2: {MIN_H2}-{MAX_H2}")

        if is_article_sufficient(content):
            print(
                "Article already satisfies "
                "the competitive content requirements."
            )

            print("No Groq call is necessary.")
            print("article.json will not be modified.")

            print("=" * 70)
            print("CONTENT UPGRADE COMPLETE")
            print("=" * 70)

            return 0

        reasons = []

        if current_words < MIN_WORDS:
            reasons.append(
                f"word count below {MIN_WORDS}"
            )

        if current_words > MAX_WORDS:
            reasons.append(
                f"word count above {MAX_WORDS}"
            )

        if current_h2 < MIN_H2:
            reasons.append(
                f"H2 count below {MIN_H2}"
            )

        if current_h2 > MAX_H2:
            reasons.append(
                f"H2 count above {MAX_H2}"
            )

        print("Upgrade required because:")

        for reason in reasons:
            print(f"  - {reason}")

        generated = generate_upgrade(api_key, article)

        print("Groq returned an upgraded article.")

        validated = validate_generated_article(
            article,
            generated,
        )

        print("Generated article passed validation.")

        updated_article = build_updated_article(
            article,
            validated,
        )

        save_article(updated_article)

        print_article_stats(
            "Final",
            validated["content_markdown"],
        )

        print("Updated fields:")
        print("  - title")
        print("  - meta_description")
        print("  - content_markdown")
        print("  - tags")
        print("  - word_count")

        print("Preserved fields:")

        preserved_fields = [
            "keyword",
            "specific_angle",
            "slug",
            "image_queries",
            "images",
            "image",
            "image_file",
            "photographer",
            "photographer_url",
            "pexels_url",
            "image_source_url",
            "image_id",
            "generated_at",
        ]

        for field in preserved_fields:
            if field in article:
                print(f"  - {field}")

        print(
            f"Saved upgraded article to: {ARTICLE_PATH}"
        )

        print("=" * 70)
        print("CONTENT UPGRADE COMPLETE")
        print("=" * 70)

        return 0

    except KeyboardInterrupt:
        print("", file=sys.stderr)
        print("Operation cancelled.", file=sys.stderr)

        return 130

    except Exception as exc:
        print("", file=sys.stderr)
        print("CONTENT UPGRADE FAILED", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "The original article.json was not "
            "replaced with the failed Groq output.",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
