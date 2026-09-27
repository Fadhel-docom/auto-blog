#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
ARTICLE=ROOT/'article.json'
MODEL=os.getenv('OPENAI_MODEL','gpt-5.6')
MIN_WORDS,MAX_WORDS=1500,2300

SYSTEM='''You are the senior editorial quality controller for Home Organization Ideas. Review the near-final English article and six selected images before publication. Check usefulness, specificity, originality, natural English, repetition, factual caution, title/meta quality, SEO without keyword stuffing, and image relevance. Do not approve thin, repetitive, deceptive, scraped, or search-manipulation content. Return ONLY JSON with decision PASS, REPAIR, or REJECT; reason; revised_title; revised_meta_description; revised_content_markdown; bad_image_indexes. Use REPAIR only for a targeted textual correction and return the complete corrected content. Put 1-based indexes of clearly irrelevant, duplicate, misleading, or unsuitable images in bad_image_indexes. Do not invent facts, studies, experts, prices, or quotes.'''.strip()

def words(s): return len(re.findall(r'\b[\w’\-]+\b',s or ''))

def call(article):
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key: raise RuntimeError('OPENAI_API_KEY unavailable; publication is blocked')
    images=[]
    for i,x in enumerate(article.get('images') or [],1):
        if isinstance(x,dict): images.append({'index':i,'query':x.get('query',''),'source_url':x.get('image_source_url',''),'width':x.get('width'),'height':x.get('height')})
    payload={'model':MODEL,'temperature':0.15,'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':json.dumps({'keyword':article.get('keyword',''),'angle':article.get('specific_angle',''),'title':article.get('title',''),'meta_description':article.get('meta_description',''),'word_count':words(article.get('content_markdown','')),'content_markdown':article.get('content_markdown',''),'hero_image':article.get('image',''),'images':images},ensure_ascii=False)}],'response_format':{'type':'json_object'}}
    r=requests.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=payload,timeout=180)
    r.raise_for_status()
    c=(r.json().get('choices') or [{}])[0].get('message',{}).get('content','')
    if isinstance(c,list): c=''.join(x.get('text','') for x in c if isinstance(x,dict))
    if not c: raise RuntimeError('OpenAI returned empty review')
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
    if bad: raise RuntimeError('OpenAI rejected image indexes: '+','.join(map(str,bad)))
    if decision=='PASS': return 0
    if decision=='REPAIR':
        content=str(review.get('revised_content_markdown','')).strip()
        title=str(review.get('revised_title','')).strip() or article.get('title','')
        meta=str(review.get('revised_meta_description','')).strip() or article.get('meta_description','')
        if not content or not MIN_WORDS<=words(content)<=MAX_WORDS: raise RuntimeError('Invalid OpenAI repair')
        article['title']=title; article['meta_description']=meta; article['content_markdown']=content
        ARTICLE.write_text(json.dumps(article,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return 0
    raise RuntimeError('OpenAI quality decision: '+(decision or 'UNKNOWN'))

try: sys.exit(main())
except Exception as e:
    print('OPENAI QUALITY GATE: BLOCKED: '+str(e),file=sys.stderr); sys.exit(1)