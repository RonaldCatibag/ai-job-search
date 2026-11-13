#!/usr/bin/env python3
"""Independent local ATS discovery worker. Fetching is deterministic; reviews use the controller."""
import argparse,concurrent.futures,datetime,fcntl,hashlib,importlib.util,json,os,signal,subprocess,sys,threading,traceback,urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
BASE=Path.home()/'local-ai';ROOT=Path.home()/'ai-job-search';DATA=BASE/'projects/ai-job-search/dashboard/discovery';DATA.mkdir(parents=True,exist_ok=True)
STOP=threading.Event()
def stamp():return datetime.datetime.now(ZoneInfo('Asia/Manila')).isoformat(timespec='seconds')
def write_status(**values):
    global status
    status.update(values,updated_at=stamp(),pid=os.getpid());temp=DATA/'status.tmp';temp.write_text(json.dumps(status,indent=2)+'\n');temp.replace(DATA/'status.json')
def command(args):
    r=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=120)
    if r.returncode:raise RuntimeError((r.stderr or r.stdout)[-1800:])
    return json.loads(r.stdout)
def queue_review(evidence_directory):
    base='http://127.0.0.1:8765'
    with urllib.request.urlopen(base+'/api/jobs',timeout=10) as r:payload=json.load(r)
    ids=[j['id'] for j in payload['jobs'] if str(j.get('evidence_file','')).startswith(str(evidence_directory)+'/') and j['status'] in ['researching','ready_to_apply']]
    if not ids:return {'queued':0}
    req=urllib.request.Request(base+'/api/controller',data=json.dumps({'action':'queue','job_ids':ids}).encode(),headers={'Content-Type':'application/json','X-Tracker-Token':payload['token']})
    with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
def scan_once():
    spec=importlib.util.spec_from_file_location('worldwide_scan',BASE/'scripts/worldwide_job_scan.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    facts=json.loads((ROOT/'documents/applications/confirmed_application_fields.json').read_text()).get('fields',{})
    excluded={'tookitaki',*(str(x).casefold() for x in facts.get('excluded_employers',[]))}
    boards=[b for b in module.BOARDS if b[0].casefold() not in excluded]
    for row in [('G2i Inc.','ashby','g2i'),('Constructor','ashby','constructor'),('Metacognition','ashby','metacognitionai'),('Xero','ashby','xero'),('Career Team Enterprises','greenhouse','cteph')]:
        if row not in boards and row[0].casefold() not in excluded:boards.append(row)
    out=BASE/'discovery-runs'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f');out.mkdir(parents=True)
    cache=BASE/'cache/job-search';cache.mkdir(parents=True,exist_ok=True)
    write_status(phase='fetching',started_at=stamp(),sources_total=len(boards),sources_done=0,run_directory=str(out),last_error=None)
    hits=[];sources=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(module.scan,b,cache) for b in boards]
        for future in concurrent.futures.as_completed(futures):
            result=future.result();hits.extend(result.pop('role_hits'));sources.append(result);write_status(sources_done=len(sources),last_source=result['company'])
    (out/'discovered.json').write_text(json.dumps(hits,indent=2)+'\n')
    selected=command([sys.executable,ROOT/'tools/scrape_state.py','candidates','--results',out/'discovered.json'])
    rows=selected.pop('selected');rows=[r for r in rows if r['company'].casefold() not in excluded]
    # Deduplicate location aliases already consolidated in earlier runs.
    state=json.loads((ROOT/'job_scraper/seen_jobs.json').read_text()).get('seen',{})
    aliases={v['url'].rstrip('/') for old in state.values() for v in old.get('location_variants',[]) if v.get('url')}
    rows=[r for r in rows if r['url'].rstrip('/') not in aliases]
    write_status(phase='saving_evidence',discovered=len(hits),new_candidates=len(rows))
    evidence=out/'postings';evidence.mkdir();stored=[];guard_errors=[]
    for row in rows:
        if STOP.is_set():break
        key=hashlib.sha256(row['url'].encode()).hexdigest()[:16];raw=evidence/(key+'.html');raw.write_text(row.pop('body',''))
        clean=evidence/(key+'.txt');guard=evidence/(key+'-guard.json')
        try:
            from posting_guard import guard as inspect_posting
            cleaned,verdict=inspect_posting(raw.read_text(),'html');clean.write_text(cleaned+'\n');guard.write_text(json.dumps(verdict,indent=2)+'\n')
        except Exception as e:
            guard.write_text(json.dumps({'error':str(e)})+'\n');guard_errors.append({'company':row['company'],'url':row['url'],'error':str(e)});continue
        pub=row.get('posted_date');pub=pub[:10] if isinstance(pub,str) else None
        row.update(first_seen=stamp()[:10],posted_date=pub,deadline=None,fit='medium',status='new',portal='employer-careers',source='cli',discovery_method='public_employer_api',evidence_file=str(clean),guard_file=str(guard),job_country=row.get('location','Unverified'),employer_country='Unverified',salary='Undisclosed / review source compensation',notes='Discovered by local worker. Remote policy, pay, required experience and overlap need review. '+('Publication date '+pub+'; may be older than 14 days.' if pub else 'Publication date unavailable; not claimed fresh.'),eligibility='Location listed on employer board; Philippines eligibility requires review')
        stored.append(row)
    (out/'fetched-jobs.json').write_text(json.dumps(stored,indent=2)+'\n')
    result=command([sys.executable,ROOT/'tools/scrape_state.py','store','--results',out/'fetched-jobs.json']) if stored else {'added':[]}
    queue_result=None
    try:queue_result=queue_review(out)
    except Exception as e:queue_result={'error':str(e),'note':'Jobs saved; review queue unavailable'}
    report={'checked_at':stamp(),'scope':'Configured public employer ATS boards; not the entire internet','sources':sources,'deduplication':selected,'stored':result,'review_queue':queue_result,'guard_errors':guard_errors,'jobs':stored}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    write_status(phase='idle',last_completed_at=stamp(),last_new_jobs=len(result.get('added',[])),last_review_queue=queue_result,source_errors=sum('error' in s for s in sources),guard_error_count=len(guard_errors),report_path=str(out/'report.json'),next_scan_at=(datetime.datetime.now(ZoneInfo('Asia/Manila'))+datetime.timedelta(seconds=interval)).isoformat(timespec='seconds'))
    print(json.dumps({'at':stamp(),'new_jobs':len(result.get('added',[])),'sources':len(sources),'review_queue':queue_result,'report':str(out/'report.json')}),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--interval-seconds',type=int,default=3600);ap.add_argument('--once',action='store_true');a=ap.parse_args();interval=max(900,a.interval_seconds)
    lock=(DATA/'worker.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('Discovery worker already running')
    status={'role':'job-discovery','phase':'starting','model':'HTTP discovery; local Qwen review via application controller','interval_seconds':interval,'scope':'Configured employer boards, including worldwide and country-labelled remote roles'}
    signal.signal(signal.SIGTERM,lambda *_:STOP.set());signal.signal(signal.SIGINT,lambda *_:STOP.set())
    write_status()
    while not STOP.is_set():
        try:scan_once()
        except Exception as e:write_status(phase='error',last_error=str(e)[:1500]);traceback.print_exc()
        if a.once or STOP.wait(interval):break
    write_status(phase='stopped')
