#!/usr/bin/env python3
import csv, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
KEYWORDS = ROOT / "keywords.csv"
ARTICLE = ROOT / "article.json"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
MIN_WORDS, MAX_WORDS = 1700, 2300

SYSTEM = """You are the senior editor for Home Organization Ideas. Write a genuinely useful, human-sounding English article. Never mention AI, automation, models, providers, prompts, or generation. Never invent statistics, studies, expert claims, quotes, prices, or credentials. Avoid filler, repetition, vague advice, and keyword stuffing. Explain practical decisions, tradeoffs, examples, common mistakes, and maintenance. Return ONLY JSON with keys: keyword, specific_angle, title, meta_description, content_markdown, image_queries, tags, h2_headings, faq. content_markdown must be 1700-2300 words with exactly 10 H2 headings. image_queries exactly 6 distinct concrete Pexels-ready queries. faq 4-6 items. title <=68 characters. meta_description 140-158 characters."""

def load_topic():
    with KEYWORDS.open('r', encoding='utf-8-sig', newline='') as f: rows=list(csv.DictReader(f))
    for row in rows:
        if str(row.get('Status','')).strip().lower() == 'pending': return row['Keyword'].strip()
    return 'fresh home organization idea for small spaces'

def slugify(s):
    s=re.sub(r'[^a-z0-9\s-]','',s.lower()); return re.sub(r'\s+','-',s).strip('-')[:70].strip('-')

def validate(a):
    req=['keyword','specific_angle','title','meta_description','content_markdown','image_queries','tags','h2_headings','faq']
    if any(not a.get(k) for k in req): raise ValueError('Missing required field')
    words=len(re.findall(r'\b\w+\b',a['content_markdown']))
    if not MIN_WORDS <= words <= MAX_WORDS: raise ValueError(f'Word count {words} outside {MIN_WORDS}-{MAX_WORDS}')
    if len(re.findall(r'^##\s+.+$',a['content_markdown'],re.M)) != 10: raise ValueError('Expected exactly 10 H2 sections')
    if len(a['image_queries']) != 6 or len({x.lower().strip() for x in a['image_queries']}) != 6: raise ValueError('Expected 6 unique image queries')
    if not 4 <= len(a['faq']) <= 6: raise ValueError('Expected 4-6 FAQs')
    if len(a['title']) > 68: raise ValueError('Title too long')
    if not 140 <= len(a['meta_description']) <= 158: raise ValueError('Meta description length invalid')
    if len(a['h2_headings']) != 10: raise ValueError('Expected 10 h2_headings')

def call_openai(topic):
    key=os.getenv('OPENAI_API_KEY')
    if not key: raise RuntimeError('OPENAI_API_KEY unavailable')
    r=requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'},json={'model':MODEL,'temperature':0.5,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':f'Focus keyword/topic: {topic}
Write a polished, specific article with a clear promise, practical systems, examples, tradeoffs, mistakes, checklist, FAQs, and maintenance routine. Do not pad.'}],'response_format':{'type':'json_object'}},timeout=180)
    r.raise_for_status(); return json.loads(r.json()['choices'][0]['message']['content'])

def call_openrouter(topic):
    key=os.getenv('OPENROUTER_API_KEY')
    if not key: raise RuntimeError('OPENROUTER_API_KEY unavailable')
    payload={'model':OPENROUTER_MODEL,'temperature':0.5,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':f'Focus keyword/topic: {topic} Write a polished, specific article with a clear promise, practical systems, examples, tradeoffs, mistakes, checklist, FAQs, and maintenance routine. Do not pad.'}],'response_format':{'type':'json_object'}}
    r=requests.post('https://openrouter.ai/api/v1/chat/completions',headers={'Authorization':f'Bearer {key}','Content-Type':'application/json','HTTP-Referer':'https://fadhel-docom.github.io/auto-blog/','X-Title':'Home Organization Ideas'},json=payload,timeout=240)
    r.raise_for_status()
    txt=r.json()['choices'][0]['message']['content']
    txt=re.sub(r'^```(?:json)?\\s*|\\s*```$','',txt.strip(),flags=re.S)
    return json.loads(txt)
def save(a,topic,provider):
    a['slug']=slugify(a['title']); a['generated_at']=datetime.now(timezone.utc).isoformat(); a['word_count']=len(re.findall(r'\b\w+\b',a['content_markdown'])); a['h2_count']=10; a['images']=[]; a['image']=''; a['generation_provider']=provider
    with ARTICLE.open('w',encoding='utf-8') as f: json.dump(a,f,ensure_ascii=False,indent=2); f.write('\\n')
    print(f"Generated: {a['title']}"); print(f"Provider: {provider}"); print(f"Words: {a['word_count']} | H2: 10 | Images planned: 6")

def main():
    topic=load_topic()
    for name,fn in [('OpenAI',call_openai),('OpenRouter Free',call_openrouter)]:
        try: a=fn(topic); validate(a); save(a,topic,name); return
        except Exception as exc: print(f'{name} failed; trying next provider: {exc}',file=sys.stderr)
    raise RuntimeError('All editorial providers failed; no article published.')

if __name__=='__main__':
    try: main()
    except Exception as exc: print(f'GENERATION FAILED: {exc}',file=sys.stderr); sys.exit(1)