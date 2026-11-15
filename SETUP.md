# Installation and operation

## 1. Prerequisites and safety

Use Python 3.11+ (tested with 3.12), or Docker Engine with Compose v2. Use the existing checkout: cloud tasks are already isolated; do not create a Git worktree unless explicitly requested. No command in this guide stops, deletes, upgrades, or edits an existing n8n container or workflow. Port 5678 is never used by this service. No credentials are needed for demo mode.

From the repository root:

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
```

Edit `.env` locally. Set a strong `API_TOKEN`; leave `DEMO_MODE=true`. Never commit `.env`, service-account JSON, attachments, or SQLite files. For local Python startup install dotenv support with `pip install 'uvicorn[standard]>=0.30,<1'`, or export variables explicitly. Docker Compose loads `.env` without an extra package.

```bash
.venv/bin/internships demo
.venv/bin/pytest -q
# Environment defaults to demo; use the same token in authenticated requests.
API_TOKEN=local-demo-token .venv/bin/uvicorn internship_assistant.api:app --host 127.0.0.1 --port 8018 --no-access-log
```

In another terminal, use your actual locally configured token:

```bash
curl -fsS http://127.0.0.1:8018/health
curl -fsS -H "Authorization: Bearer $API_TOKEN" http://127.0.0.1:8018/opportunities
curl -fsS -X POST -H "Authorization: Bearer $API_TOKEN" http://127.0.0.1:8018/notify/new
```

The last action returns preview text in demo; it never contacts Telegram. Demo imports are idempotent. Data is stored in `data/demo.sqlite`; live mode uses `data/live.sqlite`.

## 2. Docker

```bash
mkdir -p secrets
docker compose config --quiet
docker compose up -d --build assistant
```

Only this project's new service is started. Set `ASSISTANT_PORT` if 8018 is occupied. Host publishing binds to loopback. Docker persists the two databases in its own named volume. Mount credentials/attachments in `secrets/` and refer to `/app/secrets/...` paths in `.env`. Do not put real documents in `data/demo/`.

## 3. Reuse existing n8n Community Edition

No n8n container is included. On your own Docker host, identify the existing n8n container and its user-defined Docker network using `docker ps` and `docker inspect`. If a suitable existing network is present, set `N8N_NETWORK` to that network's exact name and run:

```bash
docker compose -f compose.yaml -f compose.n8n-network.yaml up -d --build assistant
```

This attaches only the new service to the existing network. It does not modify n8n. If n8n has no usable existing network, run the Python service at an address it already can reach and edit workflow HTTP URLs accordingly; do not change existing containers automatically. Never use `localhost:8018` from inside n8n's container to reach another container.

Import the four JSON files in `workflows/` through n8n's import UI. They are inactive. For each HTTP node select a new **Header Auth** credential: name `Authorization`, value `Bearer <your API_TOKEN>`. The default base URL is `http://assistant:8000`; edit each node if using another reachable address. No paid n8n Variables feature is required. Test with Manual Trigger first, then activate the three scheduled workflows. Schedule timezone: Asia/Riyadh (discovery every four hours, monitor/sync 07:00, notifications 08:00). Configure schedules in `config/discovery.json` and regenerate repository JSON using `python docs/generate_workflows.py`; reimport only after review. Workflow 04 is manual review only; it cannot send email. Import/activation was not tested against an actual n8n instance during development.

HTTP nodes retry transient failures up to three times. Inspect n8n executions for failures. Monitor responses also contain per-source errors; a successful HTTP response does not mean every source was collected. Rerun failed sources after fixing configuration. Never add retries to the email-send action.

## 4. Live sources and ethical collection

Set `DEMO_MODE=false` in the process environment or Compose `.env` and restart only this project's service. Review source URLs, website terms, permission to automate, and rate limits before adding them. The crawler checks robots.txt and stops conservatively on inaccessible robots, redirects, unsupported content, or disallowed paths. Use the canonical HTTPS URL if a site redirects. It has a 2-second minimum per-host delay, respects crawl-delay, and retries transient responses. CAPTCHA, login, or JavaScript-only sites require manual review; no bypass is provided.

`config/sources.json` retains reviewed priority/manual targets and selector overrides. Broad discovery now searches the official Brave API and credential-free Wikidata directory using `config/discovery.json`, then incrementally verifies website/career/contact pages and structured JobPosting listings. Search-only ownership, technical departments, availability and eligibility remain uncertain unless evidence supports them. Organizations without vacancies remain outreach targets. Read [docs/DISCOVERY.md](docs/DISCOVERY.md) for provider setup, secure key configuration, source verification, limits, and error/status interpretation.

For monitoring, add reviewed opportunity blocks to a source:

```json
{
  "name": "Your verified organization",
  "city": "Riyadh",
  "sector": "Software",
  "url": "https://official.example/",
  "opportunities": [{
    "source_url": "https://official.example/careers/internship",
    "selector": "#internship-detail",
    "title": "Exact title visible on page",
    "kind": "COOP",
    "eligibility": "Unknown",
    "evidence": "",
    "apply_url": "https://official.example/apply",
    "email": "",
    "email_kind": "",
    "opens": "",
    "closes": ""
  }]
}
```

Replace example values with reviewed real sources; do not add this fictional example as a live listing. The title must appear in the selected block; application URLs must be present in its links. Email, evidence, and ISO dates must occur verbatim. Leave dates blank if ambiguous or formatted differently, until reviewed; the system never infers a deadline. Non-Unknown eligibility requires a quoted evidence excerpt and a human-reviewed classification. Summer compatibility depends on duration, dates, student status, and university requirements, never the COOP label alone. Eligibility and email labels are reviewed configuration, not independently certified by software.

Existing IDs are preserved. New cross-source aliases match employer/title/location and normalized source/application URLs or employer-scoped structured job identifiers; distinct explicit posting years stay separate. Tracking survives repeated imports. Ambiguous duplicates remain visible for manual review; no fuzzy-match guarantee is claimed. Expired/removed pages are reported as errors, not silently deleted.

## 5. Google Sheets

Create a dedicated spreadsheet and a Google Cloud service account with Sheets API enabled. Share the spreadsheet with that account as editor. Store its JSON under ignored `secrets/`. Set `GOOGLE_APPLICATION_CREDENTIALS` to its local/mounted path and `GOOGLE_SHEET_ID` to the spreadsheet ID. Alternatively use supported Google Application Default Credentials. Run `/sync` in live mode.

The service creates and rewrites only `Companies`, `Opportunities`, `ApplicationMethods`, `Tracking`, `Applications`, `CompanyMethods`, and `DiscoveryCandidates` tabs. **These tabs are dedicated mirrors: their contents are replaced.** Do not store other work in them. SQLite is authoritative; sheet edits are not imported. RAW writes prevent spreadsheet formula injection. Back up SQLite before migrations. Share the spreadsheet only with intended users; drafts and statuses are personal data.

## 6. Telegram

Create a bot with Telegram BotFather. Set `TELEGRAM_BOT_TOKEN` and your `TELEGRAM_CHAT_ID` securely, start a conversation with the bot, then invoke `/notify/new` in live mode. Daily summaries include full per-opportunity application instructions. New/changed alerts are fingerprinted; daily summaries and reminders deduplicate per Saudi calendar date. Deadline reminders occur 7, 3, 1, and 0 days before a known closing date; follow-ups appear when due. No scheduling is performed inside Python: use n8n or an external scheduler.

Telegram delivery and the local receipt cannot be atomically committed; a crash after delivery may produce a duplicate next run. Oversized messages are truncated at Telegram-safe length, so keep source titles concise. Do not delete the database merely to rerun notifications.

## 7. Optional AI and future email

Without AI credentials, local keyword relevance explains recommendations. Set `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL` to enable an OpenAI-compatible chat endpoint. The authenticated recommendation endpoint returns advisory score, category, and explanation. It never drops low-ranked opportunities or changes eligibility. AI calls send source titles/requirements to the configured provider. Network/provider failures are explicit API errors.

Application APIs: create a personalized draft with `POST /applications/draft` (`opportunity_id`, `applicant_summary`), inspect it with `GET /applications`, then explicitly approve with `POST /applications/{id}/approve`. Portal-only and general-contact opportunities require manual action. Only verified recruitment addresses are eligible for email drafting.

Sending stays disabled unless live mode and `EMAIL_SENDING_ENABLED=true` are both set. For future use, configure SMTP over TLS on port 465, sender/auth credentials, and both PDF attachment paths. Set `EMAIL_DAILY_LIMIT` (default 5 UTC-day attempts). Explicit approval is required unless the operator deliberately sets `EMAIL_AUTO_APPROVED=true`. This flag is global pre-approval; keep false unless that policy is intended. Invoke `/applications/{id}/send` manually; no shipped workflow invokes it. Duplicate attempts are blocked, including uncertain deliveries; inspect SMTP logs and reconcile manually. Review and edit applicant_summary before drafting; no CV parsing or invented personal claims. A draft per opportunity is immutable through the API; correcting it requires a reviewed code/admin operation. No real application emails were sent in development.

## 8. Credentials and networking

Required for live functionality only: Telegram bot/chat, Google credential file/sheet, optional AI key, and future SMTP credentials/documents. API_TOKEN is needed for API operations even in demo. Store these securely in environment settings/local ignored files, never in workflow JSON. Allow official source hosts plus `sheets.googleapis.com`, the Google credential token endpoint (typically `oauth2.googleapis.com`), `api.telegram.org`, your AI provider, and your SMTP host/port. SMTP requires raw TCP/TLS access; HTTP proxy secrets alone may not support it. No live provider integrations are claimed verified without credentials.

### Docker behind a trusted HTTPS inspection proxy

If pip succeeds on the host but Docker fails certificate verification, supply your administrator-approved combined CA bundle as a BuildKit secret:

```bash
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t internship-assistant:local .
```

The optional `proxy_ca` secret is available only during dependency installation and is not copied into image layers. Normal builds need no secret. Keep TLS verification enabled; never use `--trusted-host` to bypass it. Live runtime requests may also need a read-only mounted trusted CA bundle and `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` pointing to it, depending on the host's network. Do not bake session-specific proxy addresses or credentials into the image.

## 9. Broad discovery upgrade

Back up live SQLite before upgrading. New tables/indexes are additive; existing tracked IDs and applications are retained. Set `DISCOVERY_CONFIG=config/discovery.json`; optionally add `BRAVE_SEARCH_API_KEY` securely. Wikidata needs no key, but is a sparse directory rather than a full vacancy search fallback. Allow `query.wikidata.org`, `api.search.brave.com`, and the official/ATS domains actually needed. The current managed environment denied the Wikidata CONNECT request; live broad discovery is not claimed verified here. Missing provider access yields a partial report rather than synthetic results. See [docs/DISCOVERY.md](docs/DISCOVERY.md) for complete commands and settings.

Configured source entries are research targets by default, not certified official sites. After independently checking a website, mark its source entry `"reviewed": true` to enable official-source contact classification in automated discovery. Existing reviewed-selector monitoring remains supported.
