#!/usr/bin/env python3
import os, subprocess, time, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:11434/api/version'
def running():
    try:
        with urllib.request.urlopen(URL,timeout=2) as r: return r.status==200
    except Exception: return False
def start():
    if running(): return
    unit=Path.home()/'.config/systemd/user/roleflow-ollama.service'
    if unit.exists():
        subprocess.run(['systemctl','--user','start','roleflow-ollama.service'],check=True)
        for _ in range(60):
            if running(): return
            time.sleep(1)
        raise SystemExit('Ollama service failed; check journalctl --user -u roleflow-ollama')
    env=os.environ.copy()
    env.update(OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS=str(ROOT/'models'), OLLAMA_CONTEXT_LENGTH='4096', OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_FLASH_ATTENTION='1', OLLAMA_KV_CACHE_TYPE='q8_0', OLLAMA_NO_CLOUD='1')
    with (ROOT/'ollama.log').open('ab') as log:
        p=subprocess.Popen([str(ROOT/'runtime/ollama/bin/ollama'),'serve'],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    for _ in range(60):
        if running(): return
        if p.poll() is not None: break
        time.sleep(1)
    raise SystemExit('Ollama did not start; see '+str(ROOT/'ollama.log'))
if __name__=='__main__':
    start()
    print('Ollama ready: http://127.0.0.1:11434')
