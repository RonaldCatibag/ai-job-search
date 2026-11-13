# Roleflow local dashboard

Start in Ubuntu / WSL:

```bash
cd ~/ai-job-search
python3 tools/application_tracker.py
```

Open http://localhost:8765 in your Windows browser. Keep the terminal running; Ctrl+C stops the server.

The app reads the saved job queue, the existing Current leads table in documents/applications/README.md, and job_search_tracker.csv. Imported submission statuses are labeled as existing records and are not newly verified. Manual status changes are stored in ~/local-ai/projects/ai-job-search/dashboard/tracker.sqlite3 with activity history. Canonical application statuses also update the CSV tracker. Researching/ready/skipped statuses remain in the dashboard store. Back up both the SQLite file and CSV.

Only mark Applied after you have submitted externally; a newly applied status requires confirmation and a date. Manual status edits do not send applications. The Automation view controls a durable worker that can review through local Ollama and dispatch supported form adapters. Only a verified form receipt or sent-email evidence marks Applied. The country fields distinguish hiring region from employer/client country, which stays unverified until sourced.

Agents & system shows actual local Aider sessions, Ollama health/loaded models, NVIDIA GPU metrics and WSL CPU/memory/disk. An open session may be waiting for input. A loaded model may be idle. Metrics are read-only. Local session logs can be viewed inside the dashboard.

No third-party frontend dependencies, cloud hosting or API keys are required. Automation uses local Ollama for advisory reviews. It binds to loopback only and uses a per-server request token for status updates. It is intended for your own local computer, not public hosting.

## Email signals and review packets
The email view shows an explicitly dated, read-only snapshot from connected Gmail. It does not poll Gmail independently. Refresh snapshot reloads saved evidence. Two rejection proposals can be approved or dismissed; no status changes until an explicit approval. Delivery failures and unmatched messages are manual alerts, not inferred rejections or newly invented applications. No Gmail labels, messages or mailbox contents are modified.

The six application review packets are linked from their application details. They include confirmed form facts and unresolved requirements. Review packets do not create applied or drafted CSV statuses when final materials have not passed verification. Four Canonical roles need applicant-authored responses under the employer's declaration. Techlumas has incomplete review drafts. 3Cloud's published shift conflicts with the current availability constraint.


## Backend controller

The existing Python server starts one controller thread. SQLite stores tasks, events and pause settings alongside the application records. A process lock prevents duplicate workers. Open Automation for queue counts, current stages, model reviews, blockers, task logs and pause/resume. Queue pending applications excludes already applied and closed jobs. The authorized portal-country override restores the specific unknown-country placeholder, while keeping the country unverified and location disclosed.

Supported adapters cover ALLSTARSIT PxSeZF, Techlumas and explicitly prepared Greenhouse applications. Other tasks finish their local review and show a clear blocker until an adapter or direct verified contact exists. The four Canonical declarations and OnlineJobs identity gates remain blockers. No generic browser autofill or invented recipient is used. A backend is not evidence that applications were sent.

Run details: [controller documentation](../../tools/README_APPLICATION_CONTROLLER.md).


The Applications page now has a live background-status banner. Automation and Agents & system show the local researcher, tailorer and checker roles separately from interactive Aider sessions. Use Send to local agents for direct local instructions. A loaded-model indicator may be empty while the browser works: the model is intentionally unloaded between preparation and browser phases to reduce WSL memory use.
