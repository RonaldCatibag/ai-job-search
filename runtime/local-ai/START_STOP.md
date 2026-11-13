# Start and stop Roleflow

Ubuntu / WSL:

```bash
~/local-ai/start-roleflow
~/local-ai/stop-roleflow
```

Start runs the dashboard at http://localhost:8765, Ollama, local workers and hourly discovery. It resumes the durable queued applications. Use `start-roleflow --paused` to start without dispatching applications.

Keep the start terminal open when launching from Ubuntu. A background Windows invocation can run this foreground WSL anchor hidden; no Windows double-click launcher is installed by these scripts.

Stop pauses dispatch, backs up SQLite, stops Roleflow services and its supervisor, and saves `projects/ai-job-search/dashboard/shutdown-handoff.json`. It does not shut down Windows or unrelated WSL work. Interrupted external submissions become `submission_unknown`; queued local work remains durable.

The stop marker also blocks the systemd services from restarting merely because WSL or VS Code opens. Explicit Start removes that marker.

Startup and shutdown logs: `logs/lifecycle.jsonl`. Pending application work: `projects/ai-job-search/dashboard/resume-work.json` and `projects/ai-job-search/STATE.md`. Completed and uncertain applications are never automatically sent again.

Lever forms use the stored `https://jobs.lever.co/...` application links. The runner rejects the `.com` spelling and unrelated destinations. It waits for parsing before filling, preserves an existing Caloocan/Philippines location, logs exact application POST metadata immediately, and requires both a successful application POST and a visible employer acknowledgment with the form gone before recording Applied. CAPTCHA and verification challenges remain user actions in the visible browser; they are not bypassed or solved by the script.
