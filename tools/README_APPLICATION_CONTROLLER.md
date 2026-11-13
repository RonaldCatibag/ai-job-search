# Roleflow application controller

Start the configured backend in Ubuntu/WSL:

```bash
~/local-ai/start-roleflow
# Before shutdown:
~/local-ai/stop-roleflow
```

Open http://localhost:8765 and select Automation. One Python server runs the HTTP API and a single background controller thread. SQLite is the persistent queue; Ollama qwen3:8b supplies advisory fit reviews; Playwright handles supported forms. No Redis, Celery, separate database server or cloud model key is required. The configured deployment uses systemd user services with memory limits and a foreground WSL supervisor. Service and launcher source backups are in `runtime/local-ai/`; private runtime data is excluded. See `ROLEFLOW.md` for fresh-clone configuration.

## Stages and evidence

Queue -> local review -> supported plan -> offline dry run -> required checks -> one live submission -> employer receipt -> Applied. Runners support reviewed Greenhouse, Lever and Ashby plans, plus the initial employer-specific adapters. Required facts, changed forms, eligibility restrictions and provider verification can still block an individual application. CAPTCHA challenges require the applicant's own action; unsuccessful or uncertain attempts never count as Applied.

Model prompts and responses, plan snapshots and runner evidence are saved under `~/local-ai/projects/ai-job-search/dashboard/controller-runs/TASK/attempt-N/`. Task events and settings are in `tracker.sqlite3` in the same dashboard directory. The existing runner also appends prompt/result audit logs. These private files include candidate information and should remain outside Git.

The user authorized applications where country eligibility is unknown. That flag never converts unknown to eligible, overrides an explicit country restriction, checks declarations or changes availability. The application message must disclose Philippines location. The specific skipped portal placeholder can be restored using Queue pending applications; all other skipped roles stay archived.

A process lock allows one controller. Queue claims use a SQLite write transaction. Safe interrupted local stages resume after restart; any possible external submission becomes submission_unknown and cannot be retried through the dashboard. Saved confirmed receipts can be recorded after a crash without resending. Explicit retries of local failures are limited to five attempts. Pause takes effect before the next task or before submission; it cannot undo an external request.

## Local API

- GET /api/controller: tasks, stage counts, settings and worker health.
- GET /api/controller/events/TASK: event log.
- POST /api/controller with action queue, pause, resume or retry.
- Queue accepts optional job_ids and restore_unconfirmed_country true.
- Retry accepts task_id; never accepts arbitrary commands or filesystem paths.

Mutations require the existing per-server X-Tracker-Token, localhost Host and a same-origin Origin if provided. The server binds 127.0.0.1 only. Manual application status edits remain separate from application dispatch.

Validation:

```bash
~/local-ai/aider-env/bin/python -m unittest tests.test_application_controller tests.test_application_tracker tests.test_application_runner
```


## Local agent pipeline (2026-11-09)

Optional Codex prompt refinement -> local instruction -> controller -> Ollama qwen3:8b -> researcher -> tailorer -> checker -> supported form runner -> receipt/history. Routine instructions can be entered directly under Automation, without Codex handling each task. The current instruction box works on prepared application plans, rather than arbitrary system commands.

Three persistent logical workers share one local model and one inference slot. Models choose existing fact IDs; code renders the trusted fact text and retains confirmed form answers. Raw model prose cannot invent qualifications, change legal answers or execute shell commands. Requests, prompts, raw outputs and results are under `dashboard/local-agents/`.

Preparation finishes before browser dispatch. Model inference and application browsers share a semaphore, and the model is unloaded before browser launch. After the observed WSL memory failure, inference uses a 4096-token context, batch 128 and short keep-alive. Larger concurrency should be matched to available RAM/VRAM; the current configuration does not load three model copies.

Supported adapters now cover ALLSTARSIT, Techlumas and explicitly mapped Greenhouse roles. Schema/wording changes or unmapped required answers block before submission. Email-code challenges hold the browser up to ten minutes, with an input on the Automation card. Codes use a private transient file, are removed after consumption and are excluded from permanent prompt/result logs. The Gmail connector redacts one-time codes, so the user supplies those codes directly. CAPTCHA and required personal declarations remain individual blockers.

Applications with an uncertain external outcome are held after restart. Sent-email evidence is distinguished from employer-received form confirmations. The UI shows actual worker state, queue counts and current employer.


Held outcomes have an owner-review control: check the employer/email, confirm the application was not submitted, then Requeue verified unsent. It never marks Applied and does not automatically restart uncertain submissions. The foreground launcher is `~/local-ai/dashboard`; keep its Ubuntu terminal running. The failed scheduled launch task is disabled pending resolution of WSL process lifetime.
