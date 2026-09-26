#!/usr/bin/env python3
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
QUEUE=ROOT/"keywords.csv"
STATE=ROOT/"logs"/"publisher_state.json"

DUE_STATUSES={"pending","queued","scheduled","failed"}

def now():
    return datetime.now(timezone.utc).replace(microsecond=0)

def parse_dt(value):
    value=str(value or "").strip()
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(value.replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None

def read_rows():
    with QUEUE.open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        fields=reader.fieldnames or []
        rows=list(reader)
    if "publish_at" not in fields:
        raise RuntimeError("QUEUE_SCHEMA_MISSING: keywords.csv must contain publish_at")
    return fields,rows

def write_rows(fields,rows):
    tmp=QUEUE.with_suffix(".queue.tmp")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader(); w.writerows(rows)
    tmp.replace(QUEUE)

def due_rows(rows):
    current=now()
    result=[]
    for i,row in enumerate(rows):
        status=str(row.get("Status","")).strip().lower()
        dt=parse_dt(row.get("publish_at"))
        if status in DUE_STATUSES and dt and dt <= current:
            result.append((dt,i,row))
    result.sort(key=lambda x:(x[0],str(x[2].get("Keyword","")).lower()))
    return result

def set_output(name,value):
    out=os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out,"a",encoding="utf-8") as f:
            f.write(f"{name}={value}\n")

def main():
    if len(sys.argv)<2:
        print("usage: queue_manager.py due|finalize|status [keyword]")
        return 2
    action=sys.argv[1]
    fields,rows=read_rows()
    due=due_rows(rows)
    if action=="due":
        if not due:
            set_output("has_due","false")
            print("QUEUE: no due articles")
            return 0
        dt,i,row=due[0]
        keyword=str(row.get("Keyword","")).strip()
        if not keyword:
            raise RuntimeError(f"QUEUE_INVALID: empty keyword at row {i+2}")
        set_output("has_due","true")
        set_output("keyword",keyword.replace("%","%25").replace("\n","%0A"))
        set_output("publish_at",dt.isoformat())
        print(f"QUEUE DUE: {keyword} | publish_at={dt.isoformat()} | due_count={len(due)}")
        return 0
    if action=="finalize":
        if len(sys.argv)<3:
            raise RuntimeError("QUEUE_FINALIZE_REQUIRES_KEYWORD")
        keyword=sys.argv[2].strip().lower()
        changed=False
        published_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for row in rows:
            if str(row.get("Keyword","")).strip().lower()==keyword:
                row["Status"]="published"
                row["Date"]=published_at
                row["published_at"]=published_at
                changed=True
                break
        if not changed:
            raise RuntimeError(f"QUEUE_KEYWORD_NOT_FOUND: {sys.argv[2]}")
        write_rows(fields,rows)
        print(f"QUEUE FINALIZED: {sys.argv[2]}")
        return 0
    if action=="status":
        pending=sum(1 for r in rows if str(r.get("Status","")).strip().lower() in DUE_STATUSES)
        due=len(due_rows(rows))
        print(json.dumps({"queue_total":len(rows),"active_queue":pending,"due":due},indent=2))
        return 0
    raise RuntimeError(f"UNKNOWN_ACTION: {action}")

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"QUEUE ERROR: {exc}",file=sys.stderr)
        raise
