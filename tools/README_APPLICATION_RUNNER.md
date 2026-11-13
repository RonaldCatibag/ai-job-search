# Local application runner

First supported adapter: ALLSTARSIT job PxSeZF. This is not a universal ATS submitter.

## Dry run (default)

From `~/ai-job-search`:

```bash
~/local-ai/aider-env/bin/python tools/application_runner.py --plan documents/applications/allstarsit_part-time-linux-web-system-administrator/application_plan.json --dry-run
```

The public form is fetched using the existing robots-aware GET-only fetcher, its posting is cleaned through posting_guard, and its schema/job ID are checked. A minimal trusted copy of the controls is created locally: third-party JavaScript, links and upload handlers are not copied. Playwright fills that local form and attaches the two-page resume locally. Browser networking and service workers are disabled, consent stays unchecked, and the submit control is disabled. A screenshot and JSON result are written under `~/local-ai/logs/sessions/application-*` and indexed in the prompt/result logs. The live form fetch sends no candidate payload.

Passing a dry run validates fields, file identity and local fill mechanics. It does NOT validate employer-side uploads, JavaScript, CAPTCHA, consent, receiving systems or live submission. The replica screenshot is labelled offline and must never be represented as submission evidence.

## Live submission (implemented, not live-tested)

Only after the five `confirmed_checks` in the plan are truthfully confirmed, this explicit invocation can submit:

```bash
~/local-ai/aider-env/bin/python tools/application_runner.py --plan documents/applications/allstarsit_part-time-linux-web-system-administrator/application_plan.json --submit --confirm-job-id PxSeZF
```

The five checks cover Philippine eligibility, schedule compatibility, the USD 40/hour target, concurrent work, and personal-data consent. Null/false/unrecognised values block before network/browser work, with one explicit user-policy exception: `application_policy.allow_unconfirmed_country: true` permits a null Philippines eligibility value when the message discloses Philippines location. False eligibility still blocks. Do not turn unknown facts into true just to clear a gate. Confirm with the employer or record an explicit user decision first. The current plan has unresolved checks and therefore cannot submit.

The live browser opens the actual official form and fills it using Playwright input events. Resume selection can trigger an employer upload immediately; use live mode only when ready to share the resume. Login/CAPTCHA are not bypassed. The runner submits once, then requires a newly visible received-confirmation and hidden form; button clicks or HTTP 200 are insufficient. An uncertain outcome is `submission_unconfirmed`: check employer/email evidence and never automatically retry. Other site failures need a specific adapter update.

## Scope and audit limits

- One role and one resume per run; resume SHA-256 is pinned to the reviewed file.
- No browser cookies imported; no account/profile changes; no Gmail sends.
- Standalone runner calls do not change tracker status. The backend controller records Applied only after a verified submission receipt.
- Canonical declarations, OnlineJobs identity gates and hidden contact addresses are not bypassed by this runner.
- Salary, work authorization, identity and legal declarations are never guessed.
- Review all screenshots and payloads locally; logs contain personal data.
- Readiness rules remain in the canonical profile and application workflow; the JSON plan records role-specific confirmations, not a second candidate profile.

## Runtime

Playwright/Chromium and pypdf are installed in `~/local-ai/aider-env`. If rebuilding this environment, install the versions recorded in the dry-run session dependencies file and run `python -m playwright install chromium`. Automated checks: `python -m unittest tests.test_application_runner`.
