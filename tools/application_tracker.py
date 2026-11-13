#!/usr/bin/env python3
"""Local application dashboard. Run: python3 tools/application_tracker.py.

Imports the saved job queue, canonical CSV tracker and existing application README.
Persists UI updates/history in SQLite outside Git. Canonical application statuses
are mirrored to job_search_tracker.csv. The separate controller worker dispatches supported applications.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import subprocess
import time
import shlex
import shutil
import urllib.request
import threading
from urllib.parse import urlsplit, parse_qs
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "frontend/application-tracker"
DATA = Path.home() / "local-ai/projects/ai-job-search/dashboard"
FIELDS = "date,company,sector,role,role_type,channel,status,contact_person,fit_rating,notes,cv_file,cover_letter_file,source,deadline".split(",")
CANONICAL = {"drafted", "applied", "interview", "offer", "hired", "rejected", "no_response", "offer_declined", "withdrawn"}
STATUSES = ["researching", "ready_to_apply", "drafted", "applied", "interview", "offer", "hired", "rejected", "no_response", "offer_declined", "withdrawn", "skipped", "closed"]
TOKEN = secrets.token_urlsafe(32)


def stamp():
    return datetime.now(ZoneInfo("Asia/Manila")).isoformat(timespec="seconds")


def normalize_url(value):
    try:
        u = urlsplit(value)
        if u.scheme not in ("https", "http") or not u.hostname:
            return ""
        return u.hostname.lower().removeprefix("www.") + u.path.rstrip("/")
    except ValueError:
        return ""


def identity(company, title, url=""):
    key = normalize_url(url) or (company.strip().casefold() + "|" + title.strip().casefold())
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def status_name(value):
    value = value.strip().lower().replace(" ", "_")
    return {"new": "researching", "ranked": "researching", "ready": "ready_to_apply", "ready_to_apply": "ready_to_apply", "expired": "closed", "unreachable": "researching"}.get(value, value if value in STATUSES else "researching")


def review_state(job, task=None):
    """Distinguish completed screening from an unfinished application without changing status."""
    pending=job.get("status") in {"researching","ready_to_apply","drafted"}
    if not pending:
        return dict(needs_review=False,review_complete=True,pending_submission=False,workflow_state=job.get("status"),workflow_reason="")
    if not task:
        return dict(needs_review=True,review_complete=False,pending_submission=True,workflow_state="to_review",workflow_reason="Not yet reviewed")
    state,stage,detail=task["state"],task["stage"],task.get("detail",{})
    complete=bool(detail.get("review")) or state in {"blocked","submission_unknown","awaiting_verification","completed"} or stage in {"prepare","dry_run","ready","submit","record","done"}
    phase={"submission_unknown":"verify_submission","awaiting_verification":"verification_required","failed":"review_failed" if not complete else "failed","blocked":"blocked","running":"working","queued":"queued"}.get(state,state)
    return dict(needs_review=not complete,review_complete=complete,pending_submission=True,workflow_state=phase,workflow_reason=detail.get("reason", ""))


def read_sources(root):
    jobs = {}
    def merge(job):
        key = identity(job["company"], job["title"], job.get("url", ""))
        previous = jobs.get(key, {})
        previous.update({k: v for k, v in job.items() if v not in (None, "")})
        previous["id"] = key
        jobs[key] = previous
    queue = root / "job_scraper/seen_jobs.json"
    if queue.exists():
        data = json.loads(queue.read_text(encoding="utf-8"))
        for key, item in data.get("seen", {}).items():
            if "tookitaki" in item.get("company", "").lower():
                continue
            merge(dict(company=item.get("company", "Unknown company"), title=item.get("title", "Untitled role"), url=item.get("url", ""), location=item.get("location", "Unverified"), employer_country=item.get("employer_country") or "Unverified", job_country=item.get("job_country") or ("Philippines" if "philippines" in item.get("location", "").lower() else "Worldwide" if re.search(r"worldwide|global",item.get("location", ""), re.I) else "Unverified"), salary=item.get("salary") or item.get("salary_status", "Undisclosed / unverified"), status=status_name(item.get("status", "new")), fit=item.get("fit", "unrated"), notes=item.get("fit_notes") or item.get("review_notes") or item.get("description", ""), deadline=item.get("deadline") or "", source_label="Saved job queue", source_key=key, source_status=item.get("status", "new"), applied_date=""))
            metadata = {field: item[field] for field in ("eligibility", "location_verdict", "schedule", "review_notes", "evidence_file", "guard_file", "source_api", "location_variants", "provider", "board", "job_id", "second_job_suitability") if field in item}
            jobs[identity(item.get("company", "Unknown company"), item.get("title", "Untitled role"), item.get("url", ""))].update(metadata)
    for plan_path in sorted((root / "documents/applications").glob("*/application_plan.json")):
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("adapter") in {"allstarsit-pxsezf", "techlumas-devops", "greenhouse-selected"} and "tookitaki" not in plan.get("company", "").casefold():
            merge(dict(company=plan["company"], title=plan["title"], url=plan["url"], status="researching", source_label="Prepared application plan", location=plan.get("location", "Remote; Philippines eligibility unconfirmed"), salary="Undisclosed / unverified", notes=plan.get("message", "Prepared application; review its role-specific disclosures."), plan_file=str(plan_path.relative_to(root)), evidence_file=plan.get("posting_evidence", ""), cv_file=plan.get("resume", "")))
    # The first README table is a pre-existing application record, not live submission evidence.
    readme = root / "documents/applications/README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        section = text.split("## Current leads", 1)[-1].split("\n## ", 1)[0]
        for line in section.splitlines():
            if not line.startswith("|"):
                continue
            cols = [v.strip() for v in line.strip("|").split("|")]
            if len(cols) < 6 or " - " not in cols[0] or not normalize_url(cols[1]):
                continue
            company, _, title = cols[0].partition(" - ")
            label = cols[4].lower()
            status = "applied" if label.startswith("applied") else "closed" if label.startswith("closed") else status_name(label)
            merge(dict(company=company, title=title, url=cols[1], location=cols[2], salary=cols[3], status=status, source_status=cols[4], source_label="Existing application README", notes=cols[5], applied_date="", source_record_note="Imported from an existing workspace record; submission was not reverified by this dashboard."))
    tracker = root / "job_search_tracker.csv"
    if tracker.exists():
        with tracker.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if not row.get("company") or "tookitaki" in row["company"].lower():
                    continue
                merge(dict(company=row["company"], title=row.get("role", ""), url=row.get("source", ""), status=status_name(row.get("status", "")), source_status=row.get("status", ""), source_label="Application tracker CSV", notes=row.get("notes", ""), cv_file=row.get("cv_file", ""), cover_letter_file=row.get("cover_letter_file", ""), applied_date=row.get("date", ""), deadline=row.get("deadline", ""), fit_rating=row.get("fit_rating", "")))
    for manifest in sorted((root/"documents/applications").glob("review_batch_*.json")):
        for role in json.loads(manifest.read_text(encoding="utf-8")).get("roles",[]):
            key=identity(role.get("company",""),role.get("title",""),role.get("url",""))
            if key in jobs:
                for field in ("review_file","preparation_status","blockers","employer_country","employer_country_source","job_country","cv_review_file","cover_review_file"):
                    if field in role:jobs[key][field]=role[field]
    return jobs


class Store:
    def __init__(self, root=ROOT, data=DATA):
        self.root, self.data = Path(root), Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data / "tracker.sqlite3"
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS updates (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS email_actions (message_id TEXT PRIMARY KEY, action TEXT NOT NULL, timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, timestamp TEXT NOT NULL, from_status TEXT, to_status TEXT NOT NULL, note TEXT NOT NULL);""")

    def connect(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def list_jobs(self):
        jobs = read_sources(self.root)
        with self.connect() as db:
            for key, body, updated_at in db.execute("SELECT id,data,updated_at FROM updates"):
                # Keep locally tracked records even if a source listing is later removed.
                data = json.loads(body)
                if key in jobs:
                    for field in ("status", "notes", "applied_date", "source_label"):
                        if field in data:jobs[key][field]=data[field]
                else:
                    jobs[key] = data
                jobs[key]["updated_at"] = updated_at
        tasks={}
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='automation_tasks'").fetchone():
                for key,state,stage,raw,updated in db.execute("SELECT job_id,state,stage,detail,updated_at FROM automation_tasks"):
                    tasks[key]=dict(state=state,stage=stage,detail=json.loads(raw),updated_at=updated)
        result = []
        for key, job in jobs.items():
            job.update(review_state(job,tasks.get(key)))
            if key in tasks:job["review_updated_at"]=tasks[key]["updated_at"]
            job.setdefault("id", key)
            for field, default in (("employer_country", "Unverified"), ("job_country", "Unverified"), ("location", "Unverified"), ("salary", "Undisclosed / unverified"), ("notes", ""), ("fit", "unrated"), ("applied_date", "")):
                job.setdefault(field, default)
            # Country is a hiring region, never an inferred company headquarters.
            if job["job_country"] == "Unverified":
                if "philippines" in job["location"].lower(): job["job_country"] = "Philippines"
                elif re.search(r"worldwide|global", job["location"], re.I): job["job_country"] = "Worldwide"
                elif "APAC" in job["location"]: job["job_country"] = "APAC ? verify countries"
            for field, kind in (("cv_file", "cv"), ("cover_letter_file", "cover"), ("review_file", "review"), ("cv_review_file", "cv_review"), ("cover_review_file", "cover_review")):
                path = self.file_path(job, kind)
                job[kind + "_available"] = bool(path)
            result.append(job)
        return sorted(result, key=lambda j: (j.get("updated_at", ""), j["company"], j["title"]), reverse=True)

    def file_path(self, job, kind):
        field = {"cv": "cv_file", "cover": "cover_letter_file", "review":"review_file", "cv_review":"cv_review_file", "cover_review":"cover_review_file"}.get(kind)
        if not field or not job.get(field): return None
        path = (self.root / job[field]).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file() or path.suffix.lower() not in {".pdf", ".tex", ".md", ".txt"}: return None
        return path

    def history(self, key):
        with self.connect() as db:
            return [dict(timestamp=t, from_status=f, to_status=s, note=n) for t,f,s,n in db.execute("SELECT timestamp,from_status,to_status,note FROM history WHERE id=? ORDER BY seq DESC",(key,))]

    def update(self, key, values):
        job = next((j for j in self.list_jobs() if j["id"] == key), None)
        if not job: raise ValueError("Job not found")
        status = values.get("status", "")
        if status not in STATUSES: raise ValueError("Unknown status")
        note = values.get("note", "").strip()
        if len(note) > 5000: raise ValueError("Note is too long")
        date = values.get("applied_date", "").strip()
        if date:
            try: datetime.strptime(date, "%Y-%m-%d")
            except ValueError: raise ValueError("Use YYYY-MM-DD for the date")
        if status == "applied" and job["status"] not in {"applied","interview","offer","hired"}:
            if values.get("confirmed_submitted") is not True or not date:
                raise ValueError("Confirm that you submitted this application and provide its submission date")
        previous = job["status"]
        timestamp = stamp()
        job.update(status=status, updated_at=timestamp)
        if date: job["applied_date"] = date
        if note: job["notes"] = (job.get("notes", "") + "\n" + timestamp[:10] + ": " + note).strip()
        job["source_label"] = "Local dashboard update"
        if status in CANONICAL:
            self.write_tracker(job, note)
        with self.connect() as db:
            db.execute("INSERT INTO updates(id,data,updated_at) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at", (key,json.dumps(job),timestamp))
            db.execute("INSERT INTO history(id,timestamp,from_status,to_status,note) VALUES(?,?,?,?,?)",(key,timestamp,previous,status,note))
        return job

    def email_items(self):
        path=self.data/"email_snapshot.json"
        data=json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(last_checked=None,items=[],continuous_polling=False)
        jobs=self.list_jobs()
        with self.connect() as db:actions={key:action for key,action in db.execute("SELECT message_id,action FROM email_actions")}
        result=[]
        for source in data.get("items",[]):
            item=dict(source)
            # Prefer exact company/title match. A mailbox sender alone never creates a job.
            matched=[j for j in jobs if j["company"].casefold()==item.get("company","").casefold() and j["title"].casefold()==item.get("role","").casefold()]
            item["job_id"]=matched[0]["id"] if len(matched)==1 else None
            item["current_status"]=matched[0]["status"] if len(matched)==1 else None
            item["action"]=actions.get(item.get("message_id"),"pending")
            desired=item.get("proposed_status")
            item["can_apply"]=bool(item["job_id"] and source.get("full_body_read") and desired in {"applied","interview","offer","rejected"} and item["current_status"] not in {"hired","rejected","no_response","offer_declined","withdrawn"} and desired!=item["current_status"] and item["action"]=="pending")
            result.append(item)
        data["items"]=result
        return data

    def email_action(self,message_id,action):
        if action not in {"apply","dismiss"}:raise ValueError("Unknown email action")
        item=next((x for x in self.email_items()["items"] if x.get("message_id")==message_id),None)
        if not item:raise ValueError("Email evidence not found")
        if item["action"]!="pending":raise ValueError("This email has already been reviewed")
        if action=="apply":
            if not item["can_apply"]:raise ValueError("No unambiguous status update is available; review this application manually")
            note="Email evidence "+item["date"]+": "+item["signal"]+" ? "+item["subject"]+" (message "+item["message_id"]+")"
            self.update(item["job_id"],dict(status=item["proposed_status"],note=note))
        with self.connect() as db:db.execute("INSERT INTO email_actions(message_id,action,timestamp) VALUES(?,?,?)",(message_id,action,stamp()))
        return dict(action=action,message_id=message_id)

    def write_tracker(self, job, note):
        path = self.root / "job_search_tracker.csv"
        lock = self.root / ".application-tracker.lock"
        with lock.open("a") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX)
            fields, rows = list(FIELDS), []
            if path.exists():
                with path.open(newline="",encoding="utf-8") as stream:
                    reader=csv.DictReader(stream);fields=list(reader.fieldnames or FIELDS);rows=list(reader)
                for field in FIELDS:
                    if field not in fields:fields.append(field)
            matches=[row for row in rows if row.get("company", "").casefold()==job["company"].casefold() and row.get("role", "").casefold()==job["title"].casefold()]
            row=matches[-1] if matches else {field:"" for field in fields}
            if not matches:rows.append(row)
            row.update(company=job["company"],role=job["title"],status=job["status"],source=job.get("url", ""))
            if job.get("applied_date"):row["date"]=job["applied_date"]
            if note:row["notes"]=(row.get("notes", "")+"; "+stamp()[:10]+": "+note).strip("; ")
            for field in ("cv_file","cover_letter_file","deadline"):
                if job.get(field):row[field]=job[field]
            temp=path.with_suffix(".csv.tmp")
            with temp.open("w",newline="",encoding="utf-8") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
                stream.flush();os.fsync(stream.fileno())
            temp.replace(path)


_CPU_LOCK = threading.Lock()
_CPU_SAMPLE = None


def system_monitor():
    global _CPU_SAMPLE
    cpu_percent = None
    try:
        fields = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        total, idle = sum(fields[:8]), fields[3] + fields[4]
        with _CPU_LOCK:
            if _CPU_SAMPLE:
                dt, di = total - _CPU_SAMPLE[0], idle - _CPU_SAMPLE[1]
                cpu_percent = round(100 * (dt - di) / dt, 1) if dt > 0 else 0
            _CPU_SAMPLE = total, idle
    except (OSError, ValueError): pass
    memory = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            name, value = line.split(":", 1)
            if name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}: memory[name] = int(value.split()[0]) * 1024
    except (OSError, ValueError): pass
    agents = []
    try:
        ps = subprocess.run(["ps", "-eo", "pid=,ppid=,pcpu=,rss=,etime=,args="], capture_output=True, text=True, timeout=3)
        processes = {}
        for line in ps.stdout.splitlines():
            parts = line.strip().split(None, 5)
            if len(parts) == 6:
                processes[int(parts[0])] = parts
        for pid, parts in processes.items():
            args = shlex.split(parts[5])
            if not any(a.endswith("/aider") or a == "aider" for a in args[:2]): continue
            parent = processes.get(int(parts[1]), ["", "", "", "", "", ""])[5]
            role = next((r for r in ("plan", "build", "review") if re.search(r"project-ai\s+"+r+r"(?:\s|$)", parent)), "assistant")
            model = args[args.index("--model")+1] if "--model" in args else "unverified"
            history = args[args.index("--chat-history-file")+1] if "--chat-history-file" in args else ""
            session = Path(history).parent.name if "/logs/sessions/" in history else None
            agents.append(dict(pid=pid,role=role,model=model,cpu_percent=float(parts[2]),memory_bytes=int(parts[3])*1024,elapsed=parts[4],state="session_open",activity="Session open; may be waiting for input",session_id=session))
    except (OSError, ValueError, subprocess.SubprocessError): pass
    ollama = dict(online=False,models=[],error=None)
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps",timeout=2) as response: data=json.load(response)
        ollama.update(online=True,models=[dict(name=m.get("name"),size=m.get("size"),size_vram=m.get("size_vram"),context_length=m.get("context_length"),expires_at=m.get("expires_at")) for m in data.get("models",[])])
    except Exception as exc:ollama["error"]="Local Ollama is unavailable"
    gpu = None
    try:
        result=subprocess.run(["nvidia-smi","--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw","--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=3)
        if result.returncode==0:
            name,util,used,total,temp,power=[v.strip() for v in result.stdout.splitlines()[0].split(",")]
            gpu=dict(name=name,utilization=float(util),memory_used_mb=float(used),memory_total_mb=float(total),temperature_c=float(temp),power_w=float(power))
    except (OSError,ValueError,IndexError,subprocess.SubprocessError):pass
    sessions=[]
    base=Path.home()/"local-ai/logs/sessions"
    if base.exists():
        for path in sorted((p for p in base.iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime,reverse=True)[:12]:
            transcript=path/"conversation.md"
            sessions.append(dict(id=path.name,has_transcript=transcript.exists(),updated_at=datetime.fromtimestamp(path.stat().st_mtime,ZoneInfo("Asia/Manila")).isoformat(timespec="seconds"),open=any(a["session_id"]==path.name for a in agents)))
    discovery=None
    discovery_file=Path.home()/"local-ai/projects/ai-job-search/dashboard/discovery/status.json"
    try:
        if discovery_file.is_file() and discovery_file.stat().st_size<100000:
            discovery=json.loads(discovery_file.read_text())
            pid=int(discovery.get("pid",0))
            command=(Path("/proc")/str(pid)/"cmdline").read_bytes() if pid>0 else b""
            discovery["alive"]=b"job_discovery_agent.py" in command
            if not discovery["alive"]:discovery["phase"]="offline"
    except (OSError,ValueError,TypeError):
        if discovery is not None:discovery["alive"]=False;discovery["phase"]="offline"
    disk=shutil.disk_usage(ROOT)
    return dict(checked_at=stamp(),discovery_worker=discovery,agents=agents,ollama=ollama,gpu=gpu,cpu_percent=cpu_percent,cpu_cores=os.cpu_count(),memory=memory,disk=dict(total=disk.total,free=disk.free),sessions=sessions,activity_note="An open session may be waiting for input. A loaded model may be idle. GPU utilization is system-wide.")


class Handler(BaseHTTPRequestHandler):
    store: Store
    controller = None
    def log_message(self, fmt, *args): pass
    def send(self, status, body, content_type="application/json; charset=utf-8"):
        if not isinstance(body, bytes):body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(body)
    def valid_host(self):
        return self.headers.get("Host", "").split(":",1)[0] in {"localhost","127.0.0.1"}
    def do_GET(self):
        if not self.valid_host():return self.send(403,{"error":"Localhost access only"})
        url=urlsplit(self.path)
        try:
            if url.path=="/api/local-agents":return self.send(200,self.controller.local_agents.snapshot())
            if url.path=="/api/controller":return self.send(200,self.controller.snapshot())
            if url.path.startswith("/api/controller/events/"):return self.send(200,dict(events=self.controller.events(url.path.rsplit("/",1)[1])))
            if url.path=="/api/email":return self.send(200,self.store.email_items())
            if url.path=="/api/monitor":
                data=system_monitor();data["local_agents"]=self.controller.local_agents.snapshot() if self.controller and self.controller.local_agents else None
                return self.send(200,data)
            if url.path.startswith("/api/session/"):
                session_id=url.path.rsplit("/",1)[1]
                if not re.fullmatch(r"[a-zA-Z0-9-]{1,100}",session_id):return self.send(400,{"error":"Invalid session"})
                path=Path.home()/"local-ai/logs/sessions"/session_id/"conversation.md"
                if not path.is_file():return self.send(404,{"error":"No conversation recorded for this session"})
                return self.send(200,dict(id=session_id,transcript=path.read_text(encoding="utf-8",errors="replace")[-18000:]))
            if url.path=="/api/jobs":return self.send(200,dict(jobs=self.store.list_jobs(),statuses=STATUSES,token=TOKEN,updated_at=stamp(),submissions_enabled=bool(self.controller),controller_enabled=bool(self.controller)))
            if url.path.startswith("/api/history/"):return self.send(200,dict(history=self.store.history(url.path.rsplit("/",1)[1])))
            if url.path=="/api/file":
                q=parse_qs(url.query);key=q.get("id",[""])[0];kind=q.get("kind",[""])[0]
                job=next((j for j in self.store.list_jobs() if j["id"]==key),{})
                path=self.store.file_path(job,kind)
                if not path:return self.send(404,{"error":"File not available"})
                return self.send(200,path.read_bytes(),"application/pdf" if path.suffix==".pdf" else "text/plain; charset=utf-8")
            assets={"/":"index.html","/app.js":"app.js","/style.css":"style.css"}
            if url.path not in assets:return self.send(404,{"error":"Not found"})
            mime={"/":"text/html; charset=utf-8","/app.js":"application/javascript; charset=utf-8","/style.css":"text/css; charset=utf-8"}[url.path]
            return self.send(200,(UI/assets[url.path]).read_bytes(),mime)
        except Exception as exc:return self.send(500,{"error":"Could not read local records: "+str(exc)})
    def do_POST(self):
        if not self.valid_host() or self.headers.get("X-Tracker-Token")!=TOKEN:return self.send(403,{"error":"Refresh the dashboard before saving"})
        origin=self.headers.get("Origin")
        if origin and origin not in {"http://"+self.headers.get("Host","")}:return self.send(403,{"error":"Cross-origin updates are not allowed"})
        if not (self.path.startswith("/api/jobs/") or self.path.startswith("/api/email/") or self.path in {"/api/controller","/api/local-agents"}):return self.send(404,{"error":"Not found"})
        try:
            size=int(self.headers.get("Content-Length","0"))
            if size<1 or size>20000:raise ValueError("Invalid request size")
            values=json.loads(self.rfile.read(size))
            if not isinstance(values,dict):raise ValueError("Expected an object")
            if self.path=="/api/local-agents":return self.send(200,self.controller.local_agents.enqueue_prepared(values.get("instruction","")))
            if self.path=="/api/controller":return self.send(200,self.controller.action(values))
            if self.path.startswith("/api/email/"):return self.send(200,self.store.email_action(self.path.rsplit("/",1)[1],values.get("action")))
            return self.send(200,dict(job=self.store.update(self.path.rsplit("/",1)[1],values)))
        except (ValueError,TypeError,AttributeError) as exc:return self.send(400,{"error":str(exc)})
        except Exception as exc:return self.send(500,{"error":"Could not save: "+str(exc)})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--port",type=int,default=8765);args=p.parse_args()
    sys.path.insert(0,str(ROOT))
    from tools.application_controller import Controller
    Handler.store=Store()
    Handler.controller=Controller(Handler.store)
    server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    Handler.controller.start()
    print(f"Application tracker: http://localhost:{args.port}",flush=True)
    print("Controller running. Supported submissions require verified checks and employer receipt. Manual status edits do not send applications.",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        Handler.controller.close()
        server.server_close()


if __name__=="__main__":main()
