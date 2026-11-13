#!/usr/bin/env python3
"""Stop only Roleflow services and preserve durable application work."""
import datetime
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import urllib.request

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / 'projects/ai-job-search/dashboard'
ROOT = BASE.parent / 'ai-job-search'
UNITS = ['roleflow-discovery.service', 'roleflow-dashboard.service', 'roleflow-ollama.service']

def stamp():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    started = stamp()
    (DATA / 'environment-stopped.json').write_text(json.dumps({'stopped_at': started, 'reason': 'User requested shutdown preparation'}) + '\n')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/jobs', timeout=4) as response:
            token = json.load(response)['token']
        request = urllib.request.Request('http://127.0.0.1:8765/api/controller', data=b'{"action":"pause"}', headers={'Content-Type': 'application/json', 'X-Tracker-Token': token})
        with urllib.request.urlopen(request, timeout=4) as response:
            json.load(response)
    except (OSError, ValueError):
        pass
    database = DATA / 'tracker.sqlite3'
    backup = DATA / 'backups' / ('before-stop-' + started.replace(':', '').replace('+', '_') + '.sqlite3')
    if database.exists():
        backup.parent.mkdir(exist_ok=True)
        with sqlite3.connect(database, timeout=15) as source, sqlite3.connect(backup) as dest:
            source.execute("UPDATE automation_settings SET value='true' WHERE key='paused'")
            source.commit()
            source.backup(dest)
    # The old foreground anchor predates the stop marker; stop only its exact script.
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            arguments = (process / 'cmdline').read_bytes().split(b'\0')
            if len(arguments) > 1 and arguments[1].decode() == str(BASE / 'dashboard-supervisor.py'):
                os.kill(int(process.name), signal.SIGTERM)
        except (OSError, UnicodeError, ProcessLookupError):
            pass
    result = subprocess.run(['systemctl', '--user', 'stop', *UNITS], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Service stop failed: ' + result.stderr)
    states = {}
    for unit in UNITS:
        state = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'ActiveState', '--value'], capture_output=True, text=True, check=True).stdout.strip()
        states[unit] = state
    if any(state not in {'inactive', 'failed'} for state in states.values()):
        raise RuntimeError('Services still active: ' + str(states))
    # Recover only after every writer/browser has stopped. Never resend here.
    if database.exists():
        sys.path.insert(0, str(ROOT))
        from tools.application_tracker import Store
        from tools.application_controller import Controller
        controller = Controller(Store(root=ROOT, data=DATA))
        controller.recover()
        with controller.store.connect() as db:
            counts = dict(db.execute('SELECT state,count(*) FROM automation_tasks GROUP BY state'))
            pending = [dict(zip(['id', 'company', 'title', 'state', 'stage'], row)) for row in db.execute("SELECT id,company,title,state,stage FROM automation_tasks WHERE state!='completed' ORDER BY created_at,id")]
    else:
        counts, pending = {}, []
    report = {'stopped_at': stamp(), 'services': states, 'queue_paused': True, 'counts': counts, 'pending_work': pending, 'backup': str(backup), 'restart_policy': 'Start services with queue paused. Unsent jobs remain queued. Uncertain submissions require receipt reconciliation before retry.'}
    (DATA / 'shutdown-handoff.json').write_text(json.dumps(report, indent=2) + '\n')
    log = BASE / 'logs/lifecycle.jsonl'
    log.parent.mkdir(exist_ok=True)
    with log.open('a') as stream:
        stream.write(json.dumps(report) + '\n')
    print(json.dumps({'stopped': True, 'services': states, 'counts': counts, 'handoff': str(DATA / 'shutdown-handoff.json')}, indent=2))

if __name__ == '__main__':
    main()
