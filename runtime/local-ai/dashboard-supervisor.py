#!/usr/bin/env python3
"""Foreground WSL anchor and supervisor for the local Roleflow services."""
import fcntl,json,os,subprocess,sys,time,urllib.request
from pathlib import Path
BASE=Path(__file__).resolve().parent
DATA=BASE/'projects/ai-job-search/dashboard'
ROOT=Path.home()/'ai-job-search'
DATA.mkdir(parents=True,exist_ok=True)
if (DATA/'environment-stopped.json').exists():
 print('Roleflow was intentionally stopped. Run ~/local-ai/start-roleflow to start it.',flush=True)
 raise SystemExit(0)
lock=(DATA/'supervisor.lock').open('a')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit(0)
with (DATA/'supervisor.log').open('ab',buffering=0) as log:
 # Keep WSL foreground streams open; child service logs remain on disk.
 print('Roleflow supervisor started; holding a foreground WSL session',flush=True)
 def health(url):
  try:
   with urllib.request.urlopen(url,timeout=3) as response:return response.status==200
  except Exception:return False
 child=None;last_start=0;last_heartbeat=0
 while True:
  if (DATA/'environment-stopped.json').exists():
   print('Roleflow intentional stop detected; supervisor exiting',flush=True)
   break
  if time.monotonic()-last_heartbeat>30:
   print("Roleflow supervisor heartbeat",flush=True);last_heartbeat=time.monotonic()
  if not health('http://127.0.0.1:11434/api/version'):
   subprocess.run([sys.executable,str(BASE/'start-ollama.py')],stdout=log,stderr=log,timeout=75)
  if not health('http://127.0.0.1:8765/api/controller'):
   if child is None or child.poll() is not None:
    if time.monotonic()-last_start<10:time.sleep(10)
    subprocess.run(['systemctl','--user','start','roleflow-dashboard.service'],check=True)
    last_start=time.monotonic()
    print('Started memory-limited backend service',flush=True)
  time.sleep(5)
