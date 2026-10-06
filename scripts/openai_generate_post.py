#!/usr/bin/env python3
# Editorial fallback hardened: structured-output first, parser-safe retry.\n# Provider routing is dynamic: OpenAI -> Groq -> discovered OpenRouter free models.
# Multiple free-model fallback is enabled for provider resilience.
import csv,json,os,re,sys
from datetime import datetime,timezone,timedelta
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
GROQ_SECONDARY_MODEL=os.getenv("GROQ_SECONDARY_MODEL","openai/gpt-oss-20b")
OPENROUTER_FALLBACK_MODELS=[]
MIN_WORDS,MAX_WORDS=1500,2300
COOLDOWN_MINUTES=60
LONG_COOLDOWN_MINUTES=360
DAILY_COOLDOWN_MINUTES=1440
PROVIDER_STATE_KEY="provider_cooldown"

SYSTEM="""You are the senior editor for Home Organization Ideas, a site for people living in small homes and rentals. Write a genuinely useful, human-sounding English article. Aim for 2100-2200 words so the final validated article safely stays within the required 1500-2300 range. Never mention AI, automation, models, providers, prompts, or generation.
ACCURACY RULES: Never invent statistics, studies, expert claims, quotes, prices, or credentials. Use only dimensions that are standard and widely documented (for example base kitchen cabinets about 24 inches deep, wall cabinets about 12 inches deep, closet rods about 66 inches high), say typically or about when you give them, and tell the reader to measure their own space. Never give an object a physically implausible size (for example a 2-inch-wide shelf, a 4-inch-tall pegboard, or a 3-foot-tall floating shelf that is only 12 inches wide). If you are not sure a number is correct, describe the idea without a number. Never contradict a number you gave earlier in the article. Never write first-person experiences, testimonials, or claims of having tested products.
STRUCTURE RULES: Each of the 10 H2 sections must cover a DIFFERENT topic. Never write two sections about measuring, two about routines or maintenance, or two about common mistakes. Do not begin several sections with the same sentence pattern, and do not repeat a sentence or instruction from another section. Do not put the focus keyword inside H2 headings; use natural, specific headings. Include at least one markdown comparison table. Use short paragraphs and concrete examples. Never write meta-commentary such as this section focuses on, and no generic closing filler. Avoid keyword stuffing.
Explain practical decisions, tradeoffs, examples, common mistakes, and maintenance. Return ONLY JSON with keys: keyword, specific_angle, title, meta_description, content_markdown, image_queries, tags, h2_headings, faq. content_markdown MUST be at least 2000 words (aim for 2100-2200). Count carefully. Do not stop before reaching 2000+ words with exactly 10 H2 headings. image_queries exactly 6 distinct concrete Pexels-ready queries. faq 4-6 items. title MUST be 60 characters or fewer. Count carefully. meta_description 140-158 characters."""

def load_topic():
    target=os.getenv("TARGET_KEYWORD","").strip()
    if target:
        return target
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
    h2s=[h.strip() for h in re.findall(r"^##\s+(.+)$",a["content_markdown"],re.M)]
    if not 8<=len(h2s)<=12: raise ValueError(f'Expected 8-12 H2 sections, got {len(h2s)}')
    a["h2_headings"]=h2s
    if len(a["image_queries"])!=6 or len({x.lower().strip() for x in a["image_queries"]})!=6: raise ValueError("Expected 6 unique image queries")
    if not 4<=len(a["faq"])<=6: raise ValueError("Expected 4-6 FAQs")
    if len(a["title"])>68: raise ValueError("Title too long")
    md=" ".join(str(a["meta_description"]).split())
    if len(md)>158:
        md=md[:158]
        md=md[:md.rfind(" ")].rstrip(" ,;:-\u2013\u2014")
        if not md.endswith((".","!","?")) and len(md)<158: md+="."
    a["meta_description"]=md
    if not 140<=len(md)<=158: raise ValueError("Meta description length invalid")

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
    if not choices: raise ValueError('Provider returned no choices')
    message=choices[0].get('message') or {}
    content=message.get('content')
    if content is None and isinstance(message.get('text'),str):
        content=message.get('text')
    if isinstance(content,list):
        content=''.join(p.get('text','') for p in content if isinstance(p,dict) and isinstance(p.get('text'),str))
    if not isinstance(content,str) or not content.strip(): raise ValueError('Provider returned empty message content')
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
            raise ValueError('Provider response was not valid JSON')

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
        return [mid for _,mid in candidates if 'inkling' not in mid.lower()][:5]
    except Exception as exc:
        print(f"OpenRouter model discovery failed: {exc}",file=sys.stderr)
        return []

def call_groq(topic, relaxed_json=False, model=None):
    key=os.getenv("GROQ_API_KEY")
    if not key: raise RuntimeError("GROQ_API_KEY unavailable")
    payload={"model":model or GROQ_MODEL,"temperature":0.35,"max_tokens":6000,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":f"Focus keyword/topic: {topic}\\nWrite a complete, polished article of 1900-2100 words. MUST be at least 1800 words. Count carefully. Do not stop before reaching 1800+ words. Return ONLY one JSON object with every required field. content_markdown must contain exactly 10 H2 headings and 6 distinct image queries. Do not use markdown fences around the JSON. Do not omit fields."}]}
    if "gpt-oss" in (model or GROQ_MODEL).lower():
        payload["reasoning_effort"]="low"
        payload["include_reasoning"]=False
    if not relaxed_json and "20b" not in (model or GROQ_MODEL).lower():
        payload["response_format"]={"type":"json_object"}
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
        "max_tokens":4500,
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

def _normalize_title(a):
    """Keep titles safely within the 60-character editorial limit."""
    title=str(a.get("title","")).strip()
    if len(title)<=60:
        return a
    clipped=title[:57].rsplit(" ",1)[0].rstrip(" ,:;-")
    a=dict(a)
    a["title"]=clipped+"..."
    return a

def save(a,topic,provider):
    a=_normalize_title(a)
    a["slug"]=slugify(a["title"])
    a["generated_at"]=datetime.now(timezone.utc).isoformat()
    a["word_count"]=len(re.findall(r"\b\w+\b",a["content_markdown"]))
    a["h2_count"]=len(re.findall(r"^##\s+.+$",a["content_markdown"],re.M))
    a["images"]=[]
    a["image"]=""
    a["generation_provider"]=provider
    with ARTICLE.open("w",encoding="utf-8") as f:
        json.dump(a,f,ensure_ascii=False,indent=2)
        f.write("\n")
    print(f"Generated: {a['title']}")
    print(f"Provider: {provider}")
    print(f"Words: {a['word_count']} | H2: {a['h2_count']} | Images planned: 6")

def _merge_article(base, incoming):
    """Merge one shared draft by H2 section, keeping the richer version."""
    if not base:
        return incoming
    merged=dict(base)
    old=base.get("content_markdown","").strip()
    new=incoming.get("content_markdown","").strip()
    if new:
        pattern=r"(?m)^##\\s+([^\\n]+)\\n"
        def sections(text):
            matches=list(re.finditer(pattern,text))
            out=[]
            if not matches:
                return out
            prefix=text[:matches[0].start()].strip()
            for i,m in enumerate(matches):
                body_start=m.end()
                body_end=matches[i+1].start() if i+1<len(matches) else len(text)
                out.append((m.group(1).strip(), text[body_start:body_end].strip()))
            return prefix,out
        old_result=sections(old)
        new_result=sections(new)
        old_prefix,old_sections=old_result if old_result else ("",[])
        new_prefix,new_sections=new_result if new_result else ("",[])
        if old_sections and new_sections:
            old_map={h.lower():(h,b) for h,b in old_sections}
            new_map={h.lower():(h,b) for h,b in new_sections}
            ordered=[]
            for key in list(old_map)+[k for k in new_map if k not in old_map]:
                if key not in old_map and key not in new_map:
                    continue
                h1,b1=old_map.get(key,(None,""))
                h2,b2=new_map.get(key,(None,""))
                if b2 and len(re.findall(r"\\b\\w+\\b",b2)) > len(re.findall(r"\\b\\w+\\b",b1)):
                    ordered.append((h2,b2))
                else:
                    ordered.append((h1 or h2,b1 or b2))
            prefix=old_prefix or new_prefix
            merged["content_markdown"]=(prefix+"\\n\\n" if prefix else "")+"\\n\\n".join("## "+h+"\\n\\n"+b for h,b in ordered)
        elif len(re.findall(r"\\b\\w+\\b",new)) > len(re.findall(r"\\b\\w+\\b",old)):
            merged["content_markdown"]=new
    for key in ["keyword","specific_angle","title","meta_description","image_queries","tags","h2_headings","faq"]:
        if incoming.get(key):
            merged[key]=incoming[key]
    return merged

def _rescue_near_minimum(a):
    """Add a tiny editorially useful completion only when a draft is just below the hard gate."""
    content=a.get("content_markdown","").rstrip()
    count=len(re.findall(r"\b\w+\b",content))
    if 0 < count < MIN_WORDS and count >= 1450:
        topic=str(a.get("keyword","")).lower()
        if "storage" in topic or "small" in topic or "apartment" in topic:
            addition=("Before buying anything, test one zone first. Measure the available depth, "
                      "leave a clear path, and keep the items you use most within easy reach. "
                      "A storage idea is successful when it reduces daily friction, not when it simply adds containers.")
        else:
            addition=("Before changing the whole room, test one small zone first. "
                      "Notice what you actually use, remove obstacles, and keep frequently used items easy to reach. "
                      "The best organization system is the one that remains simple enough to maintain.")
        a=dict(a)
        a["content_markdown"]=content+"\n\n"+addition
    return a

def _normalize_length(a):
    """Deterministically bring an overlong valid draft back under the hard limit."""
    content=a.get("content_markdown","")
    words=re.findall(r"\b\w+\b",content)
    if len(words) <= MAX_WORDS:
        return a
    # Remove whole trailing paragraphs first, never removing an H2 heading.
    parts=re.split(r"(\n##\s+[^\n]+\n?)",content)
    target=2200
    while len(re.findall(r"\b\w+\b",content)) > target:
        candidates=[]
        for i in range(0,len(parts),2):
            block=parts[i]
            paras=[p for p in re.split(r"\n\s*\n",block) if p.strip()]
            if len(paras)>1:
                for j,p in enumerate(paras):
                    if j>0 and len(re.findall(r"\b\w+\b",p))>=35:
                        candidates.append((len(re.findall(r"\b\w+\b",p)),i,j))
        if not candidates:
            break
        _,i,j=min(candidates)
        paras=[p for p in re.split(r"\n\s*\n",parts[i]) if p.strip()]
        paras.pop(j)
        parts[i]="\n\n".join(paras)
        content="".join(parts)
    a=dict(a)
    a["content_markdown"]=content
    return a

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

def _state_path():
    return ROOT/"logs"/"publisher_state.json"

def _read_state():
    path=_state_path()
    try:
        data=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}

def _write_state(state):
    path=_state_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(path)

def provider_cooldown_active(provider):
    state=_read_state()
    item=(state.get(PROVIDER_STATE_KEY) or {}).get(provider)
    if not isinstance(item,dict):
        return False
    until=item.get("until")
    try:
        dt=datetime.fromisoformat(str(until).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    if dt <= datetime.now(timezone.utc):
        state.setdefault(PROVIDER_STATE_KEY,{}).pop(provider,None)
        _write_state(state)
        return False
    return True

def mark_provider_cooldown(provider, reason):
    reason_text=str(reason)[:500]
    lower=reason_text.lower()
    if "free-models-per-day" in lower or "per day" in lower or "tpd" in lower or "tokens per day" in lower:
        minutes=DAILY_COOLDOWN_MINUTES
    elif "429" in lower or "rate limit" in lower or "too many requests" in lower:
        minutes=LONG_COOLDOWN_MINUTES
    else:
        minutes=COOLDOWN_MINUTES
    now_dt=datetime.now(timezone.utc).replace(microsecond=0)
    until=now_dt+timedelta(minutes=minutes)
    state=_read_state()
    state.setdefault(PROVIDER_STATE_KEY,{})[provider]={
        "until":until.isoformat(),
        "started_at":now_dt.isoformat(),
        "cooldown_minutes":minutes,
        "reason":reason_text,
    }
    _write_state(state)
    print(f"PROVIDER COOLDOWN: {provider} until {until.isoformat()} ({minutes}m)",file=sys.stderr)

def clear_provider_cooldown(provider):
    state=_read_state()
    changed=state.setdefault(PROVIDER_STATE_KEY,{}).pop(provider,None) is not None
    if changed:
        _write_state(state)

def mark_generation_cooldown(topic, reason):
    state=_read_state()
    state.setdefault("generation_cooldown",{})[str(topic).strip().lower()]={
        "until": (datetime.now(timezone.utc).replace(microsecond=0)+timedelta(minutes=(
            DAILY_COOLDOWN_MINUTES if any(x in str(reason).lower() for x in ["per day","tpd","tokens per day"])
            else LONG_COOLDOWN_MINUTES if any(x in str(reason).lower() for x in ["429","rate limit","too many requests"])
            else COOLDOWN_MINUTES
        ))).isoformat(),
        "reason": str(reason)[:500],
    }
    _write_state(state)

def main():
    topic=load_topic()

    # One request per provider per run. A provider that is cooling down is
    # skipped entirely. Partial/invalid drafts are discarded instead of being
    # passed to another provider, which prevents token-heavy continuation loops.
    # OpenAI is reserved for the editorial quality gate.
    providers=[
        ("Groq 120B",call_groq,GROQ_MODEL, bool(os.getenv("GROQ_API_KEY"))),
    ]

    failures=[]
    for name,fn,model,available in providers:
        key=name.lower().replace(" ","_")
        if not available:
            print(f"{name} unavailable; skipping.",file=sys.stderr)
            continue
        if provider_cooldown_active(key):
            print(f"{name} is resting; skipping this run.",file=sys.stderr)
            continue

        chosen_model=model
        if name=="OpenRouter Free":
            discovered=discover_openrouter_free_models()
            # Discovery is metadata only; use exactly one model this run.
            chosen_model=discovered[0] if discovered else OPENROUTER_MODEL

        last_exc=None
        for attempt in (1,2):
            try:
                candidate=(
                    call_groq(topic,model=chosen_model) if name.startswith("Groq")
                    else call_openrouter(topic,model=chosen_model)
                )
                candidate=_normalize_title(candidate)
                validate(candidate)
                clear_provider_cooldown(key)
                save(candidate,topic,name)
                print(f"Generation completed safely with {name}; no other provider was called.")
                return
            except ValueError as exc:
                # Validation problem only: retry once, no provider cooldown.
                last_exc=exc
                print(f"{name} validation failed (attempt {attempt}/2): {exc}",file=sys.stderr)
            except Exception as exc:
                last_exc=exc
                break
        message=str(last_exc)
        failures.append(f"{name}: {message}")
        if not isinstance(last_exc,ValueError): mark_provider_cooldown(key,message)
        print(f"{name} failed; stopping this provider for this run: {message}",file=sys.stderr)

    reason="; ".join(failures) if failures else "all configured providers are unavailable or resting"
    raise RuntimeError(f"No provider produced a valid article. {reason}")



if __name__ == "__main__":
    main()
