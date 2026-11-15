# Update only the internship assistant on Windows/Docker

Run in **the existing repository directory**, using Docker Desktop in Linux-container mode (or your existing compatible Engine). These are user-run deployment commands; development did not execute them or change any existing container/workflow.

```powershell
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git update failed; resolve local changes without resetting personal work.' }
powershell -NoProfile -File .\scripts\update-assistant.ps1
```

If your original installation used a custom Compose project name (`-p`) that is not already in its environment, supply **that same existing name**, not a new one:

```powershell
powershell -NoProfile -File .\scripts\update-assistant.ps1 -ProjectName 'YOUR_EXISTING_COMPOSE_PROJECT_NAME'
```

The helper refuses to guess if it cannot find exactly one assistant for the current project/checkout. It reads only Compose labels (not credentials) from that container and reuses its original project name and exact Compose files, including an existing n8n-network override. It preserves other .env settings while explicitly setting:

```dotenv
EMAIL_SENDING_ENABLED=false
EMAIL_AUTO_APPROVED=false
ENABLE_BRAVE_SEARCH=false
AI_PROVIDER=local
```

It validates configuration, starts only the existing assistant if needed for backup, uses SQLite's online backup API for existing demo/live databases into `data/backups/` in the same persistent volume, then executes the equivalent of:

```powershell
docker compose --project-name $existingProject <the same original -f files> up -d --no-deps --build assistant
```

The angle-bracket portion above describes the files automatically recovered by the helper; it is not an extra command to paste. Do not invent a new project name: that can select a different data volume. The helper does not run `down`, remove volumes, stop n8n, restart other services, change networks on n8n, or edit deployed workflows. It checks `/health` inside the assistant and verifies email sending is disabled. Demo/live mode remains your existing choice; it is not silently changed.

The PowerShell helper was reviewed but **not executed or parsed with PowerShell in this Linux environment**, where PowerShell is unavailable. Compose configuration, Python behavior and SQLite compatibility were tested separately. If your host policy disallows scripts, review the helper with your administrator rather than bypassing that policy. Windows/WSL path-label mismatches, missing original override files, absent required network variables, or backup failures stop the helper before a guessed deployment.

After update, these are read-only assistant-only checks (no notifications/submissions):

```powershell
docker compose exec -T -e DEMO_MODE=false assistant internships diagnose-targets
docker compose exec -T -e DEMO_MODE=false assistant internships free-source-check
```

Use the same project/override arguments if your installation needs them; a base-file-only status query must not be mistaken for a different project. Neither command claims success when egress or DNS is blocked. Do not invoke `/notify` while testing. No n8n workflow reimport is required for the existing discovery/monitor/sync routes. Optional new LinkedIn lead imports use the authenticated API and do not require altering deployed workflows.

Backups are retained in the same volume and protect against application mistakes; copy a backup to separate storage if you need disaster recovery. Do not delete the original volume. If a build fails because of your managed HTTPS proxy, use the trusted-CA BuildKit mechanism already documented in SETUP.md, with TLS verification enabled.
