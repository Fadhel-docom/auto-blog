#!/usr/bin/env python3
# Editorial fallback hardened: structured-output first, parser-safe retry.\n# Provider routing is dynamic: OpenAI -> Groq -> discovered OpenRouter free models.
# Multiple free-model fallback is enabled for provider resilience.
import csv,json,os,re,sys
from datetime import datetime,timezone
from pathlib import Path
import requests
try:
    from json_repair import repair_json
except ImportError:
    repair_json = None

ROOT=Path(__file__).resolve().parents[1]
KEYWORDS=ROOT/"keywords.csv"
ARTICLE=ROOT/"article.json"
MODEL=os.getenv("OPENAI_MODEL","gpt-5.6")
OPENROUTER_MODEL=os.getenv("OPENROUTER_MODEL","openrouter/free")
GROQ_MODEL=os.getenv("GROQ_MODEL","openai/gpt-oss-120b")
OPENROUTER_FALLBACK_MODELS=[]
MIN_WORDS,MAX_WORDS=1700,2300

SYSTEM="""You are the senior editor for Home Organization Ideas. Write a genuinely useful, human-sounding English article. Aim for 1900-2100 words so the final validated article safely stays within the required 1700-2300 range. Never mention AI, automation, models, providers, prompts, or generation. Never invent statistics, studies, expert claims, quotes, prices, or credentials. Avoid filler, repetition, vague advice, and keyword stuffing. Explain practical decisions, tradeoffs, examples, common mistakes, and maintenance. Return ONLY JSON with keys: keyword, specific_angle, title, meta_description, content_markdown, image_queries, tags, h2_headings, faq. content_markdown must be 1700-2300 words with exactly 10 H2 headings. image_queries exactly 6 distinct concrete Pexels-ready queries. faq 4-6 items. title <=68 characters. meta_description 140-158 characters."""

def load_topic():
    with KEYWORDS.open("r",encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
    for row in rows:
        if str(row.get("Status","")).strip().lower()=="pending": return row["Keyword"].strip()
    return "fresh home organization idea for small spaces"

def slugify(s):
    s=re.sub(r"[^a-z0-9\s-]","",s.lower())
    return re.sub(r"\s+","-",s).strip("-")[:70].strip("-")

def validate(a):
    req=["keyword","specific_angle","title","meta_description","content_markdown","image_queries","tags","h2_headings","faq"]
    missing=[k for k in req if not a.get(k)]
    if missing: raise ValueError("Missing required field(s): " + ", ".join(missing))
    words=len(re.findall(r"\b\w+\b",a["content_markdown"]))
    if not MIN_WORDS<=words<=MAX_WORDS: raise ValueError(f"Word count {words} outside {MIN_WORDS}-{MAX_WORDS}")
    if len(re.findall(r"^##\s+.+$",a["content_markdown"],re.M))!=10: raise ValueError("Expected exactly 10 H2 sections")
    if len(a["image_queries"])!=6 or len({x.lower().strip() for x in a["image_queries"]})!=6: raise ValueError("Expected 6 unique image queries")
    if not 4<=len(a["faq"])<=6: raise ValueError("Expected 4-6 FAQs")
    if len(a["title"])>68: raise ValueError("Title too long")
    if not 140<=len(a["meta_description"])<=158: raise ValueError("Meta description length invalid")
    if len(a["h2_headings"])!=10: raise ValueError("Expected 10 h2_headings")

def repair_json_text(s):
    out=[]
    in_string=False
    escaped=False
    i=0
    while i<len(s):
        ch=s[i]
        if escaped:
            out.append(ch); escaped=False; i+=1; continue
        if ch=='\\':
            out.append(ch); escaped=True; i+=1; continue
        if ch=='"':
            if not in_string:
                in_string=True; out.append(ch)
            else:
                j=i+1
                while j<len(s) and s[j].isspace(): j+=1
                nxt=s[j] if j<len(s) else ''
                if nxt in [',','}',']',':'] or nxt=='':
                    in_string=False; out.append(ch)
                else:
                    out.append('\\"')
            i+=1; continue
        if in_string and ch in ['\r','\n']:
            out.append('\\n')
        else: out.append(ch)
        i+=1
    return ''.join(out)

def parse_json_content(response_json):
    choices=response_json.get('choices') or []
    if not choices: raise ValueError('OpenRouter returned no choices')
    message=choices[0].get('message') or {}
    content=message.get('content')
    if content is None and isinstance(message.get('text'),str):
        content=message.get('text')
    if isinstance(content,list):
        content=''.join(p.get('text','') for p in content if isinstance(p,dict) and isinstance(p.get('text'),str))
    if not isinstance(content,str) or not content.strip(): raise ValueError('OpenRouter returned empty message content')
    content=content.strip()
    if content.startswith('```'):
        lines=content.splitlines()[1:]
        if lines and lines[-1].strip()=='```': lines=lines[:-1]
        content='\n'.join(lines).strip()
    try: return json.loads(content)
    except json.JSONDecodeError:
        if repair_json is not None:
            try:
                repaired_obj=repair_json(content, return_objects=True)
                if isinstance(repaired_obj,dict):
                    return repaired_obj
            except Exception:
                pass
        repaired=repair_json_text(content)
        try: return json.loads(repaired)
        except json.JSONDecodeError:
            start,end=repaired.find('{'),repaired.rfind('}')
            if start>=0 and end>start:
                candidate=repaired[start:end+1]
                if repair_json is not None:
                    try:
                        repaired_obj=repair_json(candidate, return_objects=True)
                        if isinstance(repaired_obj,dict):
                            return repaired_obj
                    except Exception:
                        pass
                try: return json.loads(candidate)
                except json.JSONDecodeError: pass
            raise ValueError('OpenRouter response was not valid JSON')

def call_openai(topic):
    key=os.getenv("OPENAI_API_KEY")
    if not key: raise RuntimeError("OPENAI_API_KEY unavailable")
    r=requests.post("https://api.openai.com/v1/chat/completions",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json={"model":MODEL,"temperature":0.5,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":f"Focus keyword/topic: {topic}\nWrite a polished, specific article with a clear promise, practical systems, examples, tradeoffs, mistakes, checklist, FAQs, and maintenance routine. Target 1900-2100 words. Do not pad, but do not stop early."}],"response_format":{"type":"json_object"}},timeout=180)
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])

def discover_openrouter_free_models():
    key=os.getenv("OPENROUTER_API_KEY")
    if not key: return []
    try:
        r=requests.get("https://openrouter.ai/api/v1/models",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},timeout=30)
        r.raise_for_status()
        data=r.json().get("data") or []
        candidates=[]
        for item in data:
            mid=item.get("id"); pricing=item.get("pricing") or {}; params=item.get("supported_parameters") or []
            if not mid or not mid.endswith(":free"): continue
            if str(pricing.get("prompt")) not in ("0","0.0","0.00") or str(pricing.get("completion")) not in ("0","0.0","0.00"): continue
            score=100 if "structured_outputs" in params else 0
            score += 20 if "response_format" in params else 0
            score += min(int(item.get("context_length") or 0)//10000,20)
            candidates.append((score,mid))
        candidates.sort(reverse=True)
        return [mid for _,mid in candidates[:8]]
    except Exception as exc:
        print(f"OpenRouter model discovery failed: {exc}",file=sys.stderr)
        return []

def call_groq(topic, relaxed_json=False):
    key=os.getenv("GROQ_API_KEY")
    if not key: raise RuntimeError("GROQ_API_KEY unavailable")
    payload={"model":GROQ_MODEL,"temperature":0.35,"max_tokens":6000,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":f"Focus keyword/topic: {topic}\\nWrite a complete, polished article of 1900-2100 words. Return ONLY one JSON object with every required field. content_markdown must contain exactly 10 H2 headings and 6 distinct image queries. Do not use markdown fences around the JSON. Do not omit fields."}]}
    if not relaxed_json: payload["response_format"]={"type":"json_object"}
    r=requests.post("https://api.groq.com/openai/v1/chat/completions",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=payload,timeout=240)
    if not r.ok:
        try: message=(r.json().get("error") or {}).get("message","")
        except Exception: message=r.text[:500]
        raise RuntimeError(f"Groq HTTP {r.status_code}: {message}")
    return parse_json_content(r.json())
def call_openrouter(topic, relaxed_json=False, model=None):
    model = model or OPENROUTER_MODEL
    key=os.getenv("OPENROUTER_API_KEY")
    if not key: raise RuntimeError("OPENROUTER_API_KEY unavailable")
    user_prompt=(
        f"Focus keyword/topic: {topic}\n"
        "Write a complete, polished article of 1900-2100 words. "
        "Return ONLY one JSON object with every required field. "
        "content_markdown must contain exactly 10 H2 headings and 6 distinct image queries. "
        "Do not use markdown fences around the JSON. Do not omit fields."
    )
    payload={
        "model":model,
        "temperature":0.35,
        "max_tokens":6000,
        "messages":[
            {"role":"system","content":SYSTEM},
            {"role":"user","content":user_prompt},
        ],
    }
    if not relaxed_json:
        payload["response_format"]={"type":"json_object"}
    r=requests.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","HTTP-Referer":"https://fadhel-docom.github.io/auto-blog/","X-Title":"Home Organization Ideas"},json=payload,timeout=240)
    if not r.ok:
        try:
            detail=r.json().get("error",{})
            message=detail.get("message") if isinstance(detail,dict) else str(detail)
        except Exception:
            message=r.text[:500]
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {message}")
    return parse_json_content(r.json())

def save(a,topic,provider):
    a["slug"]=slugify(a["title"])
    a["generated_at"]=datetime.now(timezone.utc).isoformat()
    a["word_count"]=len(re.findall(r"\b\w+\b",a["content_markdown"]))
    a["h2_count"]=10
    a["images"]=[]
    a["image"]=""
    a["generation_provider"]=provider
    with ARTICLE.open("w",encoding="utf-8") as f:
        json.dump(a,f,ensure_ascii=False,indent=2)
        f.write("\n")
    print(f"Generated: {a['title']}")
    print(f"Provider: {provider}")
    print(f"Words: {a['word_count']} | H2: 10 | Images planned: 6")

def _merge_article(base, incoming):
    """Merge a continuation into one shared article instead of restarting from zero."""
    if not base:
        return incoming
    merged=dict(base)
    old=base.get("content_markdown","").strip()
    new=incoming.get("content_markdown","").strip()
    if new:
        # Models are told to continue only; avoid duplicating an identical prefix.
        if old and new.startswith(old):
            merged["content_markdown"]=new
        elif old:
            merged["content_markdown"]=old+"\n\n"+new
        else:
            merged["content_markdown"]=new
    for key in ["keyword","specific_angle","title","meta_description","image_queries","tags","h2_headings","faq"]:
        if incoming.get(key):
            merged[key]=incoming[key]
    return merged

def _collaboration_prompt(topic, draft, stage):
    if not draft:
        return f"""Focus keyword/topic: {topic}
You are the first editor in a cooperative writing chain. Start the shared article.
Write ONLY valid JSON. Build the article toward 1900-2100 words, exactly 10 H2 headings, 6 unique image queries and 4-6 FAQs.
You may write the first half now (roughly 900-1200 words, headings 1-5) if needed. Do not stop because of an artificial short target; produce as much high-quality article content as the response limit safely allows.
This draft will be handed directly to another editor, who must continue it rather than restart it."""
    return f"""Focus keyword/topic: {topic}
You are stage {stage} in a cooperative editorial chain. CONTINUE THE SHARED DRAFT below; do not restart, summarize, or rewrite completed sections.
Add the next missing H2 sections and complete missing required fields. Preserve the existing useful text exactly where possible.
Target a final article of 1900-2100 words with exactly 10 H2 headings, 6 unique image queries and 4-6 FAQs.
Return ONLY one valid JSON object. If the previous editor stopped mid-article, continue naturally from its last complete sentence.

SHARED DRAFT:
{json.dumps(draft, ensure_ascii=False)}"""

def _call_cooperative(name, fn, model, topic, draft, stage):
    prompt=_collaboration_prompt(topic,draft,stage)
    if name=="OpenAI":
        return fn(prompt)
    if name=="Groq":
        return fn(prompt,relaxed_json=(stage>=2))
    return fn(prompt,relaxed_json=(stage>=2),model=model)

def main():
    topic=load_topic()
    # Cooperative chain: every available provider receives the same working
    # article. A later provider continues missing sections or reviews a complete
    # draft. No provider is treated as an isolated restart.
    providers=[
        ("OpenAI",call_openai,None, bool(os.getenv("OPENAI_API_KEY"))),
        ("Groq",call_groq,GROQ_MODEL, bool(os.getenv("GROQ_API_KEY"))),
        ("OpenRouter Free",call_openrouter,None, bool(os.getenv("OPENROUTER_API_KEY"))),
    ]

    draft=None
    successful_stages=0
    for name,fn,model,available in providers:
        if not available:
            print(f"{name} unavailable; cooperative chain will continue.",file=sys.stderr)
            continue

        models=[model]
        if name=="OpenRouter Free":
            models=discover_openrouter_free_models() or ["openrouter/free"]

        provider_finished=False
        for chosen_model in models:
            for attempt in range(3):
                try:
                    stage=successful_stages+1
                    a=_call_cooperative(name,fn,chosen_model,topic,draft,stage)
                    candidate=_merge_article(draft,a)
                    try:
                        validate(candidate)
                        draft=candidate
                        provider_finished=True
                        successful_stages += 1
                        print(f"{name} contributed successfully to the shared editorial draft.")
                        break
                    except Exception as validation_error:
                        draft=candidate
                        print(f"{name} contributed partial work; next stage will continue it: {validation_error}",file=sys.stderr)
                        raise validation_error
                except Exception as exc:
                    print(f"{name} cooperative stage attempt {attempt+1} failed: {exc}",file=sys.stderr)
                    continue
            if provider_finished:
                break

    if draft:
        validate(draft)
        save(draft,topic,"Cooperative chain")
        print(f"Cooperative editorial chain completed through {successful_stages} provider stage(s).")
        return

    raise RuntimeError("No editorial provider was available; no article published.")
if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"GENERATION FAILED: {exc}",file=sys.stderr)
        sys.exit(1)
