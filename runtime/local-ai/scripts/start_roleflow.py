#!/usr/bin/env python3
"""Start Roleflow and resume only the durable, eligible application queue."""
import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

BASE = Path(__file__).resolve().parents[1]
DATA = BASE / 'projects/ai-job-search/dashboard'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paused', action='store_true')
    args = parser.parse_args()
    (DATA / 'environment-stopped.json').unlink(missing_ok=True)
    subprocess.run(['systemctl', '--user', 'start', 'roleflow-ollama.service', 'roleflow-dashboard.service', 'roleflow-discovery.service'], check=True)
    for _ in range(60):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8765/api/jobs', timeout=2) as response:
                token = json.load(response)['token']
            request = urllib.request.Request('http://127.0.0.1:8765/api/controller', data=json.dumps({'action': 'pause' if args.paused else 'resume'}).encode(), headers={'Content-Type': 'application/json', 'X-Tracker-Token': token})
            with urllib.request.urlopen(request, timeout=3) as response:
                json.load(response)
            break
        except (OSError, ValueError):
            time.sleep(0.5)
    else:
        raise RuntimeError('Dashboard did not become ready; inspect dashboard/server.log')
    with urllib.request.urlopen('http://127.0.0.1:8765/api/controller', timeout=3) as response:
        snapshot = json.load(response)
    record = {'started_at': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds'), 'queue_paused': args.paused, 'counts': snapshot['counts'], 'policy': 'Only queued work dispatches. Unknown submissions remain held for receipt checks.'}
    (DATA / 'startup-handoff.json').write_text(json.dumps(record, indent=2) + '\n')
    with (BASE / 'logs/lifecycle.jsonl').open('a') as stream:
        stream.write(json.dumps(record) + '\n')
    print('Roleflow ready: http://localhost:8765. ' + ('Queue paused.' if args.paused else 'Saved eligible queue resumed; uncertain submissions held.'), flush=True)
    os.execv(sys.executable, [sys.executable, str(BASE / 'dashboard-supervisor.py')])

if __name__ == '__main__':
    main()
