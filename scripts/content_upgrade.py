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
FALLBACK_GROQ_MODEL = "llama-3.1-8b-instant"

MAX_RETRIES = 5

MIN_WORDS = 1500
MIN_ACCEPTABLE_WORDS = 1300
MAX_WORDS = 2400

MIN_H2 = 10
MAX_H2 = 11

MAX_ARTICLE_CHARS_IN_PROMPT = 7000


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
            f"article.json field '{field_name}' "
            "must be a string."
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
    plain = re.sub(
        r"!\[[^\]]*\]\([^)]*\)",
        " ",
        plain,
    )
    plain = re.sub(
        r"\[[^\]]*\]\([^)]*\)",
        " ",
        plain,
    )
    plain = re.sub(
        r"[#>*_~`]+",
        " ",
        plain,
    )

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
        MIN_ACCEPTABLE_WORDS <= words <= MAX_WORDS
        and MIN_H2 <= h2_count <= MAX_H2
    )


def get_status_code(
    exception: Exception,
) -> Optional[int]:
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
You are an expert long-form SEO editor and writer for an English-language website focused on:

Home Organization & Small-Space Living.

Your task is to improve an existing article.

The article already has a valid topic, keyword, title, metadata, and general direction.
You must preserve the original topic and intent while substantially improving the article's usefulness, depth, organization, and readability.

LENGTH REQUIREMENT:
- The final article must contain between 1500 and 2400 actual words.
- Aim for approximately 2000 words.
- You MUST produce at least 1800 words.
- If you finish before 1800 words, continue writing more detailed sections.
- Do NOT summarize.
- Do NOT stop early.
- Do NOT exceed 2400 words.

H2 REQUIREMENT:
- The final article must contain EXACTLY 10 H2 headings whenever possible.
- 10 H2 headings is the required target.
- 11 H2 headings are allowed only if absolutely necessary.
- Do NOT use fewer than 10 H2 headings.
- NEVER use more than 11 H2 headings.
- Every H2 must contain useful, distinct information.
- Do not create empty or extremely short H2 sections.
- Do not use an H1 inside content_markdown.

TITLE REQUIREMENT:
- The article title must be concise, specific, and easy to scan.
- Aim for 45-65 characters.
- Never exceed 70 characters unless the exact focus keyword makes this impossible.
- Avoid unnecessary words, filler, and long list-style phrasing.
- Keep the main topic or benefit clear within the first 8-10 words.
- Preserve the exact focus keyword naturally in the title.

ARTICLE STRUCTURE:
- Begin with a concise introduction.
- The introduction should naturally contain the exact focus keyword.
- Use 10 useful H2 sections (11 maximum).
- Use H3 headings only when they genuinely improve organization.
- End with a practical conclusion.
- Include a natural reader-focused CTA when appropriate.

HEADING RULES:
- H2 headings must use Markdown format: ## Heading
- H3 headings must use Markdown format: ### Heading
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
- Do not claim a specific product brand is recommended unless that brand already appears in the original article and the claim can be supported by the supplied text.
- Do not invent prices, reviews, certifications, measurements, or performance guarantees.
- If a measurement is presented as an example rather than a universal standard, make that distinction clear.

SEO:
- Preserve the exact focus keyword naturally.
- Keep the keyword in the title if it is already there.
- Ensure the exact focus keyword appears naturally in the introduction.
- Do not keyword-stuff.
- Preserve the article's search intent.
- Improve semantic coverage with closely related terms where natural.
- Do not add an artificial keyword list to the article.

IMAGES:
- Do not generate image queries.
- Do not generate image Markdown.
- Do not modify image metadata.
- Image planning happens in a separate pipeline step.

IMPORTANT:
The input article may already contain useful sections.
Do not blindly replace useful information with generic text.
Retain valuable concrete details while improving structure, depth, transitions, and completeness.

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


def build_user_prompt(
    article: Dict[str, Any],
) -> str:
    keyword = str(
        article.get("keyword", "")
    ).strip()

    specific_angle = str(
        article.get("specific_angle", "")
    ).strip()

    title = str(
        article.get("title", "")
    ).strip()

    meta_description = str(
        article.get("meta_description", "")
    ).strip()

    full_content = str(
        article.get("content_markdown", "")
    ).strip()

    tags = article.get("tags", [])

    if not isinstance(tags, list):
        tags = []

    clean_tags = []

    for tag in tags:
        if isinstance(tag, str):
            tag = tag.strip()

            if (
                tag
                and tag not in clean_tags
            ):
                clean_tags.append(tag)

    if len(full_content) > MAX_ARTICLE_CHARS_IN_PROMPT:
        content = (
            full_content[
                :MAX_ARTICLE_CHARS_IN_PROMPT
            ].rstrip()
            + "\n\n... [article continues]"
        )

        print(
            "Article content truncated for Groq prompt:"
        )
        print(
            f"  Original characters: {len(full_content)}"
        )
        print(
            f"  Sent characters: {len(content)}"
        )
    else:
        content = full_content

        print(
            "Article content did not require truncation:"
        )
        print(
            f"  Characters: {len(content)}"
        )

    prompt = f"""
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
Rewrite and improve this article while preserving its original search intent and specific topic.

The final version must:
1.  Contain between 1500 and 2400 actual words.
2.  Aim for approximately 2000 words.
3.  You MUST produce at least 1800 words.
4.  If you finish before 1800 words, continue writing more detailed sections.
5.  Do NOT summarize.
6.  Contain EXACTLY 10 H2 headings.
7.  Do NOT use 9 H2 headings.
8.  Do NOT use 11 H2 headings unless absolutely necessary.
9.  NEVER use more than 11 H2 headings.
10. Keep the exact focus keyword naturally in the title and introduction.
11. Preserve useful concrete information from the original.
12. Add depth where the original is too short or shallow.
13. Remove repetitive or low-value passages.
14. Improve transitions between sections.
15. Make every H2 section materially useful.
16. Avoid invented facts, statistics, studies, citations, quotes, prices, or unsupported claims.
17. Do not create image queries.
18. Do not create image Markdown.
19. Do not mention this editing process.
20. Do not mention AI.
21. Keep the article title concise and specific.
22. Aim for 45-65 characters and never exceed 70 characters unless the exact focus keyword makes this impossible.
23. Avoid unnecessary words, filler, and long list-style titles.

Return ONLY the JSON object requested by the system prompt.
""".strip()

    return prompt


def estimate_tokens(text: str) -> int:
    if not text:
        return 0

    return max(
        1,
        (len(text) + 3) // 4,
    )


def log_request_size(
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> None:
    total_chars = (
        len(system_prompt) + len(user_prompt)
    )
    estimated_tokens = estimate_tokens(
        system_prompt + "\n" + user_prompt
    )

    print("Groq request estimate:")
    print(f"  Model: {model}")
    print(
        f"  System prompt characters: "
        f"{len(system_prompt)}"
    )
    print(
        f"  User prompt characters: "
        f"{len(user_prompt)}"
    )
    print(
        f"  Total characters: "
        f"{total_chars}"
    )
    print(
        f"  Estimated input tokens: "
        f"{estimated_tokens}"
    )


def generate_upgrade_with_model(
    client: Groq,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> Dict[str, Any]:
    last_exception: Optional[Exception] = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            print(
                "Calling Groq for content upgrade "
                f"(model={model}, "
                f"attempt {attempt}/{MAX_RETRIES})..."
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
                temperature=0.6,
                max_tokens=5000,
                response_format={
                    "type": "json_object"
                },
            )

            if not response.choices:
                raise ValueError(
                    "Groq returned no choices."
                )

            message = response.choices[0].message
            content = getattr(
                message,
                "content",
                None,
            )

            if not content:
                raise ValueError(
                    "Groq returned an empty message."
                )

            generated = extract_json_from_response(
                content
            )

            print(
                f"Groq upgrade succeeded "
                f"with model={model}."
            )

            return generated

        except Exception as exc:
            last_exception = exc
            status_code = get_status_code(exc)

            print("Groq request failed:")
            print(f"  Model: {model}")
            print(
                f"  Attempt: "
                f"{attempt}/{MAX_RETRIES}"
            )
            print(
                f"  Status code: "
                f"{status_code}"
            )
            print(
                f"  Reason: {exc}",
                file=sys.stderr,
            )

            if status_code in (413, 429):
                if status_code == 413:
                    print(
                        "  Reason: request exceeded the "
                        "model token/request limit."
                    )
                else:
                    print(
                        "  Reason: primary model rate "
                        "limit reached."
                    )
                raise

            retryable_codes = {
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

            delay = min(
                2 ** (attempt - 1),
                30,
            )

            print(
                f"Retrying in {delay} seconds..."
            )
            time.sleep(delay)

    raise RuntimeError(
        "Groq content upgrade failed after "
        f"{MAX_RETRIES} attempts using "
        f"model '{model}': "
        f"{last_exception}"
    )


def generate_upgrade_repair(
    client: Groq,
    model: str,
    original_generated: Dict[str, Any],
    validation_error: str,
) -> Dict[str, Any]:
    repair_system_prompt = """
You are a strict final SEO editor.

You received an article that was already successfully generated, but it failed one structural validation rule.

Repair ONLY the structural problem described below.

NON-NEGOTIABLE REQUIREMENTS:
- Preserve the article topic and search intent.
- Preserve useful information and existing depth.
- Keep the final article between 1500 and 2400 actual words.
- Aim for approximately 1900-2100 words.
- The final article MUST contain exactly 10 H2 headings.
- Never produce more than 11 H2 headings.
- Do not remove useful article content merely to satisfy the heading count.
- If there are too many H2 headings, merge logically related sections or demote a secondary section to H3 while preserving its content.
- Do not invent facts, statistics, studies, citations, prices, or quotes.
- Preserve the exact focus keyword in the title and introduction.
- Return ONLY valid JSON using exactly:

{
  "title": "article title",
  "meta_description": "meta description",
  "content_markdown": "complete repaired article",
  "tags": ["tag 1", "tag 2"]
}
""".strip()

    generated_json = json.dumps(
        original_generated,
        ensure_ascii=False,
    )

    repair_user_prompt = f"""
The generated article failed validation.

VALIDATION ERROR:
{validation_error}

Repair the article now.

The most important structural target is:
EXACTLY 10 H2 headings.

Do not shorten the article below 1500 words.

CURRENT GENERATED ARTICLE:
{generated_json}

Return ONLY the repaired JSON object.
""".strip()

    print(
        "Retrying Groq content upgrade because "
        "the generated article failed validation..."
    )

    return generate_upgrade_with_model(
        client=client,
        model=model,
        system_prompt=repair_system_prompt,
        user_prompt=repair_user_prompt,
    )


def generate_upgrade(
    api_key: str,
    article: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    client = Groq(api_key=api_key)

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(article)

    log_request_size(
        GROQ_MODEL,
        system_prompt,
        user_prompt,
    )

    try:
        print("")
        print(
            f"Primary upgrade model: {GROQ_MODEL}"
        )

        return generate_upgrade_with_model(
            client=client,
            model=GROQ_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    except Exception as primary_exc:
        primary_status = get_status_code(
            primary_exc
        )

        print("", file=sys.stderr)
        print(
            "Primary content upgrade failed.",
            file=sys.stderr,
        )
        print(
            f"  Model: {GROQ_MODEL}",
            file=sys.stderr,
        )
        print(
            f"  Status code: {primary_status}",
            file=sys.stderr,
        )
        print(
            f"  Reason: {primary_exc}",
            file=sys.stderr,
        )

        if primary_status in (413, 429):
            print("")

            if primary_status == 413:
                print(
                    "413 detected: request is too large "
                    "for the primary model."
                )
            else:
                print(
                    "Primary model failed with 429."
                )

            print(
                "Switching to fallback model: "
                f"{FALLBACK_GROQ_MODEL}"
            )

            try:
                log_request_size(
                    FALLBACK_GROQ_MODEL,
                    system_prompt,
                    user_prompt,
                )

                return generate_upgrade_with_model(
                    client=client,
                    model=FALLBACK_GROQ_MODEL,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )

            except Exception as fallback_exc:
                fallback_status = get_status_code(
                    fallback_exc
                )

                print("", file=sys.stderr)
                print(
                    "Fallback content upgrade failed.",
                    file=sys.stderr,
                )
                print(
                    f"  Model: "
                    f"{FALLBACK_GROQ_MODEL}",
                    file=sys.stderr,
                )
                print(
                    f"  Status code: "
                    f"{fallback_status}",
                    file=sys.stderr,
                )
                print(
                    f"  Reason: "
                    f"{fallback_exc}",
                    file=sys.stderr,
                )

                if fallback_status in (413, 429):
                    print(
                        "Fallback model also rejected "
                        "the request."
                    )
                    print(
                        "Content upgrade will be skipped."
                    )
                    print(
                        "The original article will be preserved."
                    )
                    return None

        print(
            "Content upgrade failed after "
            "primary-model fallback handling."
        )
        print(
            "The original article will be preserved."
        )
        return None


def normalize_tags(
    raw_tags: Any,
) -> List[str]:
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]

    if not isinstance(raw_tags, list):
        return []

    tags = []

    for tag in raw_tags:
        if not isinstance(tag, str):
            continue

        tag = tag.strip()

        if (
            tag
            and tag not in tags
        ):
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
        original_article.get(
            "meta_description",
            "",
        )
    ).strip()

    original_tags = normalize_tags(
        original_article.get(
            "tags",
            [],
        )
    )

    title = generated.get("title")
    meta_description = generated.get(
        "meta_description"
    )
    content_markdown = generated.get(
        "content_markdown"
    )

    if not isinstance(title, str):
        raise ValueError(
            "Groq output field 'title' "
            "must be a string."
        )

    if not isinstance(meta_description, str):
        raise ValueError(
            "Groq output field "
            "'meta_description' must be a string."
        )

    if not isinstance(content_markdown, str):
        raise ValueError(
            "Groq output field "
            "'content_markdown' must be a string."
        )

    title = title.strip()
    meta_description = (
        meta_description.strip()
    )
    content_markdown = clean_markdown(
        content_markdown
    )

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
        original_article.get(
            "keyword",
            "",
        )
    ).strip()

    if keyword:
        if keyword.lower() not in title.lower():
            raise ValueError(
                "The upgraded title does not contain "
                "the exact focus keyword."
            )

        introduction = (
            content_markdown[:1800].lower()
        )

        if keyword.lower() not in introduction:
            raise ValueError(
                "The upgraded introduction does not "
                "contain the exact focus keyword."
            )

    words = count_words(content_markdown)
    h2_headings = extract_h2_headings(
        content_markdown
    )
    h2_count = len(h2_headings)

    print(
        f"Generated word count: {words}"
    )
    print(
        f"Generated H2 count: {h2_count}"
    )

    if words < MIN_ACCEPTABLE_WORDS:
        raise ValueError(
            "Generated article is too short: "
            f"{words} words. "
            f"Absolute minimum is "
            f"{MIN_ACCEPTABLE_WORDS}."
        )

    if words < MIN_WORDS:
        print(
            "WARNING: generated article is below "
            f"target MIN_WORDS={MIN_WORDS}: "
            f"{words} words."
        )
        print(
            "WARNING: accepting it because it meets "
            f"the absolute minimum of "
            f"{MIN_ACCEPTABLE_WORDS} words."
        )

    if words > MAX_WORDS:
        raise ValueError(
            "Generated article is too long: "
            f"{words} words. "
            f"Maximum is {MAX_WORDS}."
        )

    if h2_count < MIN_H2:
        raise ValueError(
            "Generated article has too few H2 "
            f"headings: {h2_count}. "
            f"Minimum is {MIN_H2}."
        )

    if h2_count > MAX_H2:
        raise ValueError(
            "Generated article has too many H2 "
            f"headings: {h2_count}. "
            f"Maximum is {MAX_H2}."
        )

    tags = normalize_tags(
        generated.get("tags")
    )

    if not tags:
        tags = original_tags

    if not tags:
        keyword_fallback = str(
            original_article.get(
                "keyword",
                "",
            )
        ).strip()

        if keyword_fallback:
            tags = [keyword_fallback]

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

    updated_article["title"] = (
        validated["title"]
    )
    updated_article["meta_description"] = (
        validated["meta_description"]
    )
    updated_article["content_markdown"] = (
        validated["content_markdown"]
    )
    updated_article["tags"] = (
        validated["tags"]
    )
    updated_article["word_count"] = (
        validated["word_count"]
    )

    return updated_article


def print_article_stats(
    label: str,
    content: str,
) -> None:
    words = count_words(content)
    headings = extract_h2_headings(content)

    print("")
    print(f"{label} article statistics:")
    print(f"  Words: {words}")
    print(f"  H2 headings: {len(headings)}")

    if headings:
        print("  H2 structure:")
        for index, heading in enumerate(
            headings,
            start=1,
        ):
            print(
                f"    {index}. {heading}"
            )

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
    except Exception as exc:
        print(
            f"ERROR loading article: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        original_content = get_required_string(
            article,
            "content_markdown",
        )
    except Exception as exc:
        print(
            f"ERROR reading article content: {exc}",
            file=sys.stderr,
        )
        return 1

    print_article_stats(
        "Original",
        original_content,
    )

    print(
        f"Configured target minimum words: "
        f"{MIN_WORDS}"
    )
    print(
        f"Absolute accepted minimum words: "
        f"{MIN_ACCEPTABLE_WORDS}"
    )
    print(f"Maximum words: {MAX_WORDS}")
    print(
        f"Required H2 range: "
        f"{MIN_H2}-{MAX_H2}"
    )
    print(
        f"Maximum article characters sent to Groq: "
        f"{MAX_ARTICLE_CHARS_IN_PROMPT}"
    )

    if is_article_sufficient(original_content):
        print(
            "Original article already satisfies "
            "the minimum structural requirements."
        )
        print(
            "No content upgrade is required."
        )
        print("Article remains unchanged.")
        return 0

    print(
        "Original article does not satisfy "
        "the upgrade requirements."
    )

    try:
        generated = generate_upgrade(
            api_key,
            article,
        )
    except Exception as exc:
        print(
            "Unexpected upgrade error:",
            file=sys.stderr,
        )
        print(
            f"  Reason: {exc}",
            file=sys.stderr,
        )
        print("Keeping the original article.")
        return 0

    if generated is None:
        print("")
        print(
            "No upgraded article was produced."
        )
        print(
            "Fallback behavior: using original article."
        )
        print(
            "Workflow will continue successfully."
        )
        return 0

    print("")
    print(
        "Groq returned an upgraded article."
    )

    validated = None
    validation_error = None

    try:
        validated = validate_generated_article(
            article,
            generated,
        )
    except Exception as exc:
        validation_error = str(exc)

    if validated is None:
        print("")
        print(
            "WARNING: upgraded article failed validation:",
            file=sys.stderr,
        )
        print(
            f"  Reason: {validation_error}",
            file=sys.stderr,
        )

        try:
            repaired = generate_upgrade_repair(
                client=Groq(api_key=api_key),
                model=GROQ_MODEL,
                original_generated=generated,
                validation_error=validation_error,
            )

            print("")
            print(
                "Groq returned a repaired upgraded article."
            )

            validated = validate_generated_article(
                article,
                repaired,
            )

            print(
                "Repaired article passed validation."
            )

        except Exception as repair_exc:
            print("")
            print(
                "WARNING: repaired article also failed "
                "validation:",
                file=sys.stderr,
            )
            print(
                f"  Reason: {repair_exc}",
                file=sys.stderr,
            )
            print(
                "The original article will be preserved."
            )
            print(
                "Workflow will continue successfully."
            )
            return 0

    updated_article = build_updated_article(
        article,
        validated,
    )

    try:
        save_article(updated_article)
    except Exception as exc:
        print(
            f"ERROR saving upgraded article: {exc}",
            file=sys.stderr,
        )
        return 1

    print("")
    print(
        "Content upgrade completed successfully."
    )

    print_article_stats(
        "Upgraded",
        validated["content_markdown"],
    )

    print(
        f"Final word count: "
        f"{validated['word_count']}"
    )

    if (
        validated["word_count"] < MIN_WORDS
    ):
        print(
            "WARNING: final article is below "
            f"the target {MIN_WORDS} words, "
            "but was accepted because it contains "
            f"at least {MIN_ACCEPTABLE_WORDS} words."
        )

    print(
        f"Final title: "
        f"{validated['title']}"
    )
    print(
        f"Final tags: "
        f"{', '.join(validated['tags'])}"
    )
    print(
        f"Saved upgraded article to: "
        f"{ARTICLE_PATH}"
    )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        print(
            "Interrupted by user.",
            file=sys.stderr,
        )
        sys.exit(130)
    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
