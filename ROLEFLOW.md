# Roleflow local application workspace

This private repository preserves the upstream AI Job Search framework and adds a local dashboard, persistent application controller, ATS form runners, local Ollama review workers and job discovery.

The upstream framework and its license remain in this repository. Personal profiles, resumes, application answers, tracker rows, browser state, mail credentials, model downloads and logs stay on the local machine.

## Local configuration

After a fresh clone, initialize the ignored configuration files:

```bash
python3 tools/init_local_profile.py
```

This copies the original upstream placeholders from `templates/local-profile/` only when the destination does not exist. It never overwrites your existing profile. Fill in your own information locally. Application plans and confirmed answers belong in the ignored `documents/applications/` folder; resume source JSON and generated exports are also ignored.

## Application runtime

The Linux/WSL backend runs at http://localhost:8765. Code is in `tools/` and `frontend/application-tracker/`. The selected source files under `runtime/local-ai/` back up the companion launchers and discovery worker; they omit the installed Python environment, Ollama binaries/models and all runtime data.

On the configured machine:

```bash
~/local-ai/start-roleflow
~/local-ai/stop-roleflow
```

Start resumes the durable eligible queue. Stop pauses dispatch, backs up the database and stops the local services. Interrupted or uncertain external submissions remain held for receipt checks, preventing automatic duplicate sends. CAPTCHA challenges must be completed by the applicant in the visible browser.

The runtime source backup does not install dependencies or restore private data on a new computer. Install Python dependencies and Playwright/Chromium, provision Ollama and the selected local model, restore your private configuration, and review the service templates before enabling the runtime. See `runtime/local-ai/START_STOP.md` and `tools/README_APPLICATION_CONTROLLER.md`.
