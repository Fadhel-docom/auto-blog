#!/usr/bin/env python3
import json,os,subprocess,time,urllib.error,urllib.request
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"logs"/"indexnow.json"
SITE=os.getenv("SITE_URL","https://fadhel-docom.github.io/auto-blog").rstrip("/")
KEY=os.getenv("INDEXNOW_KEY","").strip()

def save(data):
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(data,indent=2,ensure_ascii=False))

def main():
    base={"timestamp":datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    if not KEY:
        save({**base,"status":"UNAVAILABLE","reason":"INDEXNOW_KEY secret missing"})
        return 1
    if not KEY.isalnum():
        save({**base,"status":"FAILED","reason":"INDEXNOW_KEY contains unsupported characters"})
        return 1
    try:
        article=json.loads((ROOT/"article.json").read_text(encoding="utf-8"))
        slug=str(article.get("slug","")).strip()
        if not slug: raise RuntimeError("article.json slug missing")
        url=f"{SITE}/posts/{slug}/"
        key_url=f"{SITE}/{KEY}.txt"
        live=""
        for _ in range(18):
            try:
                with urllib.request.urlopen(key_url,timeout=10) as r:
                    live=r.read().decode().strip()
                if live==KEY: break
            except Exception: pass
            time.sleep(10)
        if live!=KEY:
            save({**base,"status":"FAILED","reason":"IndexNow key file not live or mismatch","key_url":key_url,"url":url})
            return 1
        payload={"host":"fadhel-docom.github.io","key":KEY,"keyLocation":key_url,"urlList":[url]}
        req=urllib.request.Request("https://api.indexnow.org/IndexNow",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json; charset=utf-8"},method="POST")
        with urllib.request.urlopen(req,timeout=30) as r:
            status=r.status
            body=r.read().decode(errors="replace")[:500]
        if status<200 or status>=300:
            raise RuntimeError(f"HTTP {status}: {body}")
        save({**base,"status":"OK","http_status":status,"url":url,"key_url":key_url})
        return 0
    except urllib.error.HTTPError as e:
        body=e.read().decode(errors="replace")[:500]
        save({**base,"status":"FAILED","reason":f"HTTP {e.code}: {body}"})
        return 1
    except Exception as e:
        save({**base,"status":"FAILED","reason":str(e)})
        return 1

if __name__=="__main__": raise SystemExit(main())
