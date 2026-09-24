#!/usr/bin/env python3
import csv, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
KEYWORDS = ROOT / "keywords.csv"
ARTICLE = ROOT / "article.json"

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")
MIN_WORDS = 1700
MAX_WORDS = 2300

def load_topic():
    with KEYWORDS.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if str(row.get("Status","")).strip().lower() == "pending":
            return row["Keyword"].strip()
    # Keep the twice-daily pipeline alive by asking for a fresh topic
    # when the finite keyword queue is exhausted.
    return "fresh home organization idea for small spaces"

def slugify(s):
    s = re.sub(r"[^a-z0-9\s-]", "", s.lower())
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:70].strip("-")

def call_openai(topic):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured in GitHub Actions secrets.")
    system = """You are the senior editor for an automated home-organization website.
Create one genuinely useful, human-sounding article. Do not mention AI, automation, Groq, or being generated.
Avoid invented statistics, fake expert claims, and unnecessary exact measurements. Give practical steps readers can actually follow.
The article must have 10 H2 sections, a useful checklist, and 4-6 FAQs. Use the focus keyword naturally.
Return ONLY valid JSON with these keys:
keyword, specific_angle, title, meta_description, content_markdown, image_queries, tags, h2_headings, faq.
image_queries must contain exactly 6 distinct, concrete photo-search queries suitable for Pexels.
content_markdown must NOT contain a top-level title (the title is separate), and should be 1700-2300 words.
The article should be specific rather than generic: explain decisions, tradeoffs, common mistakes, and a simple maintenance routine.
Use Markdown headings beginning with ## for the 10 H2 sections. Put the FAQ section in content_markdown only if useful, but still provide faq separately.
"""
    user = f"""Focus keyword/topic: {topic}

Write a polished article for readers searching for practical home organization help.
Prefer a clear promise in the title, strong opening, concrete examples, and a simple system that can be maintained.
Do not pad the article just to reach a word count."""
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "temperature": 0.5,
            "messages": [{"role":"system","content":system},{"role":"user","content":user}],
            "response_format": {"type":"json_object"},
        },
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"]
    article = json.loads(text)
    return article

def validate(a):
    required = ["keyword","specific_angle","title","meta_description","content_markdown",
                "image_queries","tags","h2_headings","faq"]
    missing = [k for k in required if not a.get(k)]
    if missing:
        raise ValueError("Missing fields: " + ", ".join(missing))
    words = len(re.findall(r"\b\w+\b", a["content_markdown"]))
    if not MIN_WORDS <= words <= MAX_WORDS:
        raise ValueError(f"Article word count {words} outside {MIN_WORDS}-{MAX_WORDS}.")
    h2 = re.findall(r"^##\s+(.+)$", a["content_markdown"], flags=re.M)
    if len(h2) != 10:
        raise ValueError(f"Expected exactly 10 H2 sections, got {len(h2)}.")
    if len(a["image_queries"]) != 6 or len(set(q.lower().strip() for q in a["image_queries"])) != 6:
        raise ValueError("Expected exactly 6 unique image queries.")
    if not 4 <= len(a["faq"]) <= 6:
        raise ValueError("Expected 4-6 FAQ items.")
    if len(a["title"]) > 68:
        raise ValueError("Title exceeds 68 characters.")
    if not 140 <= len(a["meta_description"]) <= 158:
        raise ValueError("Meta description must be 140-158 characters.")

def save(a, topic):
    a["slug"] = slugify(a["title"])
    a["generated_at"] = datetime.now(timezone.utc).isoformat()
    a["word_count"] = len(re.findall(r"\b\w+\b", a["content_markdown"]))
    a["h2_count"] = 10
    a["images"] = []
    a["image"] = ""
    with ARTICLE.open("w", encoding="utf-8") as f:
        json.dump(a, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Generated: {a['title']}")
    print(f"Keyword: {topic}")
    print(f"Words: {a['word_count']} | H2: 10 | Images planned: 6")

def main():
    topic = load_topic()
    article = call_openai(topic)
    validate(article)
    save(article, topic)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"GENERATION FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
