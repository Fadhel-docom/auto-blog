#!/usr/bin/env python3
import csv,json,os,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests

ROOT=Path(__file__).resolve().parents[1]
SITE=os.getenv("SITE_URL","https://fadhel-docom.github.io/auto-blog/").rstrip("/")+"/"
REPO=os.getenv("GITHUB_REPOSITORY","Fadhel-docom/auto-blog")
TOKEN=os.getenv("GITHUB_TOKEN","").strip()
GOAT_SITE=os.getenv("GOATCOUNTER_SITE","").strip()
GOAT_KEY=os.getenv("GOATCOUNTER_API_KEY","").strip()
INDEXNOW_KEY=os.getenv("INDEXNOW_KEY","").strip()
OUT=ROOT/"logs"/"automation_health.json"
QUEUE=ROOT/"keywords.csv"

def gh(path):
    r=requests.get("https://api.github.com"+path,headers={"Authorization":f"Bearer {TOKEN}","Accept":"application/vnd.github+json"},timeout=20)
    if not r.ok: raise RuntimeError(f"GitHub API {r.status_code}: {r.text[:300]}")
    return r.json()

def site_check():
    result={}
    for name,path in [("homepage",""),("sitemap","sitemap.xml"),("rss","index.xml")]:
        url=urljoin(SITE,path)
        try:
            r=requests.get(url,timeout=20)
            result[name]={"ok":200<=r.status_code<400,"status":r.status_code,"url":url}
        except Exception as e: result[name]={"ok":False,"error":str(e),"url":url}
    return result

def queue_check():
    with QUEUE.open("r",encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    now=datetime.now(timezone.utc)
    overdue=[]
    active=0
    for row in rows:
        status=str(row.get("Status","")).strip().lower()
        if status in {"pending","queued","scheduled","failed"}: active+=1
        raw=str(row.get("publish_at","")).strip()
        if raw:
            try:
                dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
                if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
                if dt<=now and status not in {"published"}:
                    overdue.append({"keyword":row.get("Keyword",""),"publish_at":raw,"status":status})
            except ValueError:
                overdue.append({"keyword":row.get("Keyword",""),"publish_at":raw,"status":"INVALID_PUBLISH_AT"})
    return {"total":len(rows),"active":active,"due_or_overdue":len(overdue),"overdue":overdue}

def content_check():
    posts_dir=ROOT/"content"/"posts"
    posts=[p for p in posts_dir.glob("*.md") if p.name != ".gitkeep"]
    if not posts:
        return {"status":"UNAVAILABLE","reason":"no posts found"}
    post=max(posts,key=lambda p:p.stat().st_mtime)
    text=post.read_text(encoding="utf-8")
    body=text.split("\n+++\n",1)[1] if "\n+++\n" in text else text
    words=len(re.findall(r"\b[\w’'-]+\b",body))
    images=re.findall(r"!\[[^\]]*\]\(([^\)]+)\)",body)
    h2=len(re.findall(r"^##\s+\S",body,re.M))
    faq=len(re.findall(r"question\s*=",text,re.I))
    unique_images=len(set(images))
    return {
        "status":"OK" if words>=1500 and len(images)>=5 and unique_images==len(images) and h2>=8 and faq>=4 else "FAIL",
        "post":post.name,"words":words,"inline_images":len(images),
        "unique_inline_images":unique_images,"h2":h2,"faq":faq
    }

def runs():
    data=gh(f"/repos/{REPO}/actions/runs?per_page=50&exclude_pull_requests=true")
    out={}
    for run in data.get("workflow_runs",[]):
        name=run.get("name","")
        if name in {"Scheduled Publisher","Health Monitor","Traffic Report"} and name not in out:
            out[name]={"id":run.get("id"),"status":run.get("status"),"conclusion":run.get("conclusion"),"created_at":run.get("created_at"),"updated_at":run.get("updated_at"),"url":run.get("html_url")}
    return out

def publisher_steps(latest_publisher):
    if not latest_publisher: return {}
    jobs=gh(f"/repos/{REPO}/actions/runs/{latest_publisher['id']}/jobs?per_page=100")
    result={}
    for job in jobs.get("jobs",[]):
        for step in job.get("steps",[]):
            name=str(step.get("name",""))
            low=name.lower()
            if any(k in low for k in ["quality gate","deploy github pages","submit indexnow","verify live article","publish hugo post","recovery check"]):
                result[name]={"status":step.get("conclusion") or step.get("status"),"job":job.get("name")}
    return result

def quality_gate(latest_publisher):
    steps=publisher_steps(latest_publisher)
    return steps.get("Quality Gate",{"status":"UNAVAILABLE"})

def traffic():
    if not GOAT_KEY or not GOAT_SITE: return {"status":"UNAVAILABLE","reason":"missing GOATCOUNTER_API_KEY" if not GOAT_KEY else "missing GOATCOUNTER_SITE"}
    try:
        r=requests.get(f"https://{GOAT_SITE}/api/v0/stats/total",headers={"Authorization":f"Bearer {GOAT_KEY}","Content-Type":"application/json"},timeout=20)
        if not r.ok: return {"status":"UNAVAILABLE","reason":f"HTTP {r.status_code}"}
        p=r.json()
        return {"status":"OK","visitors":p.get("total")}
    except Exception as e: return {"status":"UNAVAILABLE","reason":str(e)}

def create_alerts(issues):
    if not issues: return []
    existing=gh(f"/repos/{REPO}/issues?state=open&labels=automation&per_page=100")
    existing_titles={x.get("title") for x in existing if isinstance(x,dict)}
    created=[]
    for issue in issues:
        title=f"Automation alert: {issue['type']}"
        if title in existing_titles: continue
        r=requests.post(f"https://api.github.com/repos/{REPO}/issues",headers={"Authorization":f"Bearer {TOKEN}","Accept":"application/vnd.github+json"},json={"title":title,"body":json.dumps(issue,indent=2),"labels":["automation","health"]},timeout=20)
        if r.ok: created.append(title)
    return created

def main():
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    report={"timestamp":now,"site":SITE,"queue":{},"site_health":{},"content":{},"runs":{},"quality_gate":{},"traffic":{},"alerts":[],"issues":[]}
    try:
        report["site_health"]=site_check()
        report["queue"]=queue_check()\n        report["content"]=content_check()
        report["runs"]=runs()
        pub=report["runs"].get("Scheduled Publisher")
        report["publisher_steps"]=publisher_steps(pub)
        report["quality_gate"]=quality_gate(pub)
        report["traffic"]=traffic()
        report["secrets"]={"INDEXNOW_KEY":"OK" if INDEXNOW_KEY else "MISSING","GOATCOUNTER_API_KEY":"OK" if GOAT_KEY else "MISSING"}
        if not INDEXNOW_KEY: report["issues"].append({"type":"Secret missing","secret":"INDEXNOW_KEY"})
        if any(not x.get("ok") for x in report["site_health"].values()): report["issues"].append({"type":"Site Health failure","site_health":report["site_health"]})
        if report["queue"].get("overdue"): report["issues"].append({"type":"Due article not published","overdue":report["queue"]["overdue"]})\n        if report["content"].get("status")=="FAIL": report["issues"].append({"type":"Latest content quality failure","content":report["content"]})
        if report["quality_gate"].get("status")=="failure": report["issues"].append({"type":"Quality Gate failure","quality_gate":report["quality_gate"]})
        run=report["runs"].get("Scheduled Publisher")
        if run and run.get("conclusion")=="failure": report["issues"].append({"type":"Scheduled Publisher failure","run":run})
        for step_name in ["Quality Gate","Deploy GitHub Pages","Verify live article","Recovery check"]:
            step=report.get("publisher_steps",{}).get(step_name)
            if step and step.get("status")=="failure": report["issues"].append({"type":f"{step_name} failure","step":step})
        idx=report.get("publisher_steps",{}).get("Submit IndexNow")
        if idx and idx.get("status")=="failure": report["issues"].append({"type":"IndexNow failure","step":idx})
        if report["traffic"].get("status")=="UNAVAILABLE": report["issues"].append({"type":"GoatCounter unavailable","traffic":report["traffic"]})
        report["alerts"]=create_alerts(report["issues"])
    except Exception as exc:
        report["fatal_error"]=str(exc)
        report["issues"].append({"type":"Site Health failure","error":str(exc)})
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return 1 if report.get("issues") else 0

if __name__=="__main__": raise SystemExit(main())
