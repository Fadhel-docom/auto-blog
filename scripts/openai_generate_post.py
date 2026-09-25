#!/usr/bin/env python3
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
    if any(not a.get(k) for k in req): raise ValueError("Missing required field")
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

def call_openrouter(topic, relaxed_json=False):
    key=os.getenv("OPENROUTER_API_KEY")
    if not key: raise RuntimeError("OPENROUTER_API_KEY unavailable")
    payload={"model":OPENROUTER_MODEL,"temperature":0.5,"max_tokens":5000,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":f"Focus keyword/topic: {topic}\nWrite a polished, specific article with a clear promise, practical systems, examples, tradeoffs, mistakes, checklist, FAQs, and maintenance routine. Return ONLY one JSON object matching the required fields. Do not pad."}]}
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

def main():
    topic=load_topic()
    for name,fn in [("OpenAI",call_openai),("OpenRouter Free",call_openrouter)]:
        max_attempts=1 if name=="OpenAI" else 3
        for attempt in range(max_attempts):
            try:
                prompt_topic=topic
                if attempt>=1:
                    prompt_topic=f"{topic}\nIMPORTANT REVISION: The previous draft was below the minimum word count. Produce a complete replacement article of 1900-2100 words, with all required JSON fields and exactly 10 H2 sections."
                if name=="OpenRouter Free":
                    a=fn(prompt_topic, relaxed_json=(attempt==2))
                else:
                    a=fn(prompt_topic)
                validate(a)
                save(a,topic,name)
                return
            except Exception as exc:
                if name=="OpenRouter Free" and attempt<2:
                    print(f"{name} attempt {attempt+1} failed validation/parsing; retrying with a fresh editorial request: {exc}",file=sys.stderr)
                    continue
                if "Word count" in str(exc) and attempt==0:
                    print(f"{name} produced a short draft; retrying with a longer editorial target.",file=sys.stderr)
                    continue
                if attempt>0:
                    print(f"{name} failed after retry {attempt}; trying next provider: {exc}",file=sys.stderr)
                else:
                    print(f"{name} failed; trying next provider: {exc}",file=sys.stderr)
                break
    raise RuntimeError("All editorial providers failed; no article published.")

if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"GENERATION FAILED: {exc}",file=sys.stderr)
        sys.exit(1)
