#!/usr/bin/env python3
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"logs"/"traffic_report.json"
SITE=os.getenv("GOATCOUNTER_SITE","").strip()
KEY=os.getenv("GOATCOUNTER_API_KEY","").strip()

def report(status,**extra):
    data={"timestamp":datetime.now(timezone.utc).replace(microsecond=0).isoformat(),"status":status,**extra}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(data,indent=2,ensure_ascii=False))
    return data

def main():
    if not KEY or not SITE:
        report("UNAVAILABLE",reason="GOATCOUNTER_API_KEY missing" if not KEY else "GOATCOUNTER_SITE missing")
        return 1
    end=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    start=end-timedelta(days=1)
    url=f"https://{SITE}/api/v0/stats/total"
    try:
        r=requests.get(url,params={"start":start.isoformat(),"end":end.isoformat()},headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"},timeout=30)
        if not r.ok:
            report("UNAVAILABLE",reason=f"GoatCounter HTTP {r.status_code}",response=r.text[:500])
            return 1
        payload=r.json()
        total=payload.get("total")
        if not isinstance(total,(int,float)):
            report("UNAVAILABLE",reason="GoatCounter response did not contain a numeric total",response=payload)
            return 1
        report("OK",site=SITE,period_start=start.isoformat(),period_end=end.isoformat(),visitors=int(total),stats=payload.get("stats",[]))
        return 0
    except Exception as exc:
        report("UNAVAILABLE",reason=str(exc))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
