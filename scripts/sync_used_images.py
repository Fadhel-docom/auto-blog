#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ARTICLE=ROOT/"article.json"
OUT=ROOT/"data"/"used_images.json"

def main():
    article=json.loads(ARTICLE.read_text(encoding="utf-8"))
    images=article.get("images") or []
    existing={}
    if OUT.exists():
        try: existing=json.loads(OUT.read_text(encoding="utf-8"))
        except Exception: existing={}
    used=existing.get("images",[]) if isinstance(existing,dict) else []
    seen={str(x.get("file","")) for x in used if isinstance(x,dict)}
    for image in images:
        if not isinstance(image,dict): continue
        file=str(image.get("file","")).strip()
        if not file or file in seen: continue
        used.append({k:image.get(k,"") for k in ("file","query","photographer","photographer_url","pexels_url")})
        seen.add(file)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({"images":used,"count":len(used)},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(f"used_images.json updated: {len(used)} unique images")
if __name__=="__main__": main()
