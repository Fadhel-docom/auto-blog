#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
ARTICLE=ROOT/'article.json'
MODEL=os.getenv('GROQ_QUALITY_MODEL','openai/gpt-oss-120b')
MIN_WORDS,MAX_WORDS=1500,2300

SYSTEM='''You are the senior editorial quality controller for Home Organization Ideas. Review the near-final English article and the metadata for six selected images before publication. Check usefulness, specificity, originality, natural English, repetition, factual caution, title/meta quality, SEO without keyword stuffing, and image relevance. Do not approve thin, repetitive, deceptive, scraped, or search-manipulation content. Return ONLY JSON with decision PASS, REPAIR, or REJECT; reason; revised_title; revised_meta_description; revised_content_markdown; bad_image_indexes. Use REPAIR only for a targeted textual correction and return the complete corrected content. Put 1-based indexes of clearly irrelevant, duplicate, misleading, or unsuitable images in bad_image_indexes. Do not invent facts, studies, experts, prices, or quotes.'''.strip()

def words(s): return len(re.findall(r'\b[\w’\-]+\b',s or ''))

def call(article):
    key=os.getenv('GROQ_API_KEY','').strip()
    if not key: raise RuntimeError('GROQ_API_KEY unavailable; publication is blocked')
    images=[]
    for i,x in enumerate(article.get('images') or [],1):
        if isinstance(x,dict): images.append({'index':i,'query':x.get('query',''),'source_url':x.get('image_source_url',''),'width':x.get('width'),'height':x.get('height')})
    review_data={'keyword':article.get('keyword',''),'angle':article.get('specific_angle',''),'title':article.get('title',''),'meta_description':article.get('meta_description',''),'word_count':words(article.get('content_markdown','')),'content_markdown':article.get('content_markdown',''),'hero_image':article.get('image',''),'images':images}
    content_parts=json.dumps(review_data,ensure_ascii=False)
    for item in images:
        content_parts+=(
            f"\nIMAGE {item['index']} - query: {item.get('query','')} "
            f"source_url: {item.get('source_url','')} "
            f"dimensions: {item.get('width')}x{item.get('height')}"
        )
    payload={'model':MODEL,'temperature':0.15,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':content_parts}],'response_format':{'type':'json_object'}}
    last_error=None
    for attempt in range(4):
        try:
            r=requests.post(
                'https://api.groq.com/openai/v1/chat/completions',
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},
                json=payload,timeout=180
            )
            if r.status_code == 429:
                retry_after=r.headers.get('Retry-After','')
                try:
                    delay=max(2,min(60,int(float(retry_after))))
                except (ValueError,TypeError):
                    delay=min(60,5*(2**attempt))
                print(f'Groq transient 429; retry {attempt+1}/4 after {delay}s',file=sys.stderr)
                last_error=RuntimeError('Groq rate limited (429)')
                if attempt < 3:
                    time.sleep(delay)
                    continue
                raise last_error
            r.raise_for_status()
            c=(r.json().get('choices') or [{}])[0].get('message',{}).get('content','')
            break
        except requests.RequestException as exc:
            last_error=exc
            resp=getattr(exc,"response",None)
            if resp is not None: print("Groq error body:", resp.text[:800])
            if attempt >= 3:
                raise
            delay=min(60,5*(2**attempt))
            print(f'Groq transient request error; retry {attempt+1}/4 after {delay}s',file=sys.stderr)
            time.sleep(delay)
    else:
        raise last_error or RuntimeError('OpenAI request failed')
    if isinstance(c,list): c=''.join(x.get('text','') for x in c if isinstance(x,dict))
    if not c: raise RuntimeError('Groq returned empty review')
    return json.loads(c.strip().strip('`'))

def main():
    if not ARTICLE.exists(): raise RuntimeError('article.json not found')
    article=json.loads(ARTICLE.read_text(encoding='utf-8'))
    if len(article.get('images') or [])!=6: raise RuntimeError('Editorial gate requires exactly six images')
    n=words(article.get('content_markdown',''))
    if not MIN_WORDS<=n<=MAX_WORDS: raise RuntimeError(f'Article has {n} words outside gate')
    review=call(article)
    decision=str(review.get('decision','')).upper().strip()
    bad=review.get('bad_image_indexes') or []
    print(json.dumps({'decision':decision,'reason':review.get('reason',''),'bad_image_indexes':bad},ensure_ascii=False))
    if bad: raise RuntimeError('Groq rejected image indexes: '+','.join(map(str,bad)))
    if decision=='PASS': return 0
    if decision=='REPAIR':
        content=str(review.get('revised_content_markdown','')).strip()
        title=str(review.get('revised_title','')).strip() or article.get('title','')
        meta=str(review.get('revised_meta_description','')).strip() or article.get('meta_description','')
        if not content or not MIN_WORDS<=words(content)<=MAX_WORDS: raise RuntimeError('Invalid Groq repair')
        article['title']=title; article['meta_description']=meta; article['content_markdown']=content
        ARTICLE.write_text(json.dumps(article,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return 0
    raise RuntimeError('Groq quality decision: '+(decision or 'UNKNOWN'))

try: sys.exit(main())
except Exception as e:
    print('GROQ QUALITY GATE: BLOCKED: '+str(e),file=sys.stderr); sys.exit(1)