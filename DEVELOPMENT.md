# Development and continuation guide

## Local loop

Work in this checkout. Do not edit the older `internship-finder` project or any existing containers/workflows. Read README, SETUP, and ARCHITECTURE first. Python 3.12 was used for validation. Install `pip install -e '.[dev]'`; run `pytest -q`. Reproduce the development environment using `pip install -r requirements.lock` and `pip install --no-deps -e .`. Lockfile includes development test dependencies; refresh deliberately after verifying tests. It is a platform-specific tested environment snapshot rather than a cross-platform hash lock.

`internships demo` imports synthetic fixtures idempotently; `internships notify` previews alerts in demo. Never enable live email to run tests. API tests exercise authorization, demo ingestion, statuses, exports, and guarded applications. Source tests use controlled HTML, not fragile internet fixtures. No test contacts Telegram, Google, AI providers, or SMTP. Docker and live integrations require separate validation; passing unit tests does not establish their access.

## Adding organizations and opportunities

Edit `config/sources.json`, preserving explicit public source URLs and cities. Include startups, SMEs, banks, hospitals, research/government organizations, and any relevant technical departments. `priority` controls human review priority; it does not remove lower-priority targets. Add reviewed opportunity selectors as described in SETUP. The company discovery step discovers career links, but does not automatically crawl them or invent vacancies. Review and add them to config. Keep unverified targets distinct from opportunities. Do not commit personal contact data; institutional publicly listed emails only.

To add an adapter, extend sources.py behind the same fetcher policies and core.validate schema. Test title changes, absent selectors, blocked robots, missing dates, ambiguous eligibility, pagination, duplicate URLs, and disappearance. Never treat a score or COOP label as eligibility evidence. Avoid broad exception swallowing without reporting per-source errors.

To change data structures, add a migration path and backups before modifying tables. Keep stable IDs or explicitly migrate relationships. Notification fingerprints should exclude observation timestamps. Keep AI outputs advisory and validate JSON. Source text can contain prompt injection; do not give models tool access or secrets. Configured source URLs and AI endpoints are trusted operator settings, not arbitrary anonymous input.

## Workflows

`python docs/generate_workflows.py` regenerates the four inactive n8n workflow files. Credentials are intentionally absent; select Header Auth after importing. Community Edition compatibility avoids paid Variables and uses literal editable API URLs. No workflow deploys itself or sends email. When changing workflow node versions, test imports against the target n8n release before claiming compatibility. For unattended error alerts, configure your existing n8n error-workflow policy manually after review; API/source failures are otherwise visible in executions and returned error arrays.

## Environment variables

See `.env.example` for every setting. API_TOKEN protects action routes. DEMO_MODE selects isolated state and prohibits external notifications/SMTP; DATA_DIR controls SQLite paths. SOURCE_CONFIG selects reviewed JSON. TELEGRAM_BOT_TOKEN/CHAT_ID and GOOGLE_SHEET_ID/GOOGLE_APPLICATION_CREDENTIALS are live integration settings. AI_BASE_URL/KEY/MODEL enable optional advisory classification. EMAIL_SENDING_ENABLED, EMAIL_AUTO_APPROVED, EMAIL_DAILY_LIMIT and SMTP_*/CV_PATH/TRAINING_LETTER_PATH are future opt-in sending controls. ASSISTANT_PORT changes host publishing; N8N_NETWORK is required only for the optional external-network Compose override.

Restart only the assistant service after changing its env_file; other containers are outside this project's scope. Shell CLI does not automatically load `.env`; use exported variables, or the service through Compose. Google auth uses a credential file/ADC, not invented API tokens. Some managed environments cannot mount raw secrets or allow SMTP; report this rather than bypassing network policy.

## Troubleshooting

- 401: API_TOKEN must be set in the service and match the request Header Auth credential.
- Missing live listings: seeds contain no speculative vacancies. Add reviewed blocks; inspect `/monitor` errors and source HTML. Redirects, robots restrictions, JavaScript-only pages and selector changes require source review.
- Google 403: enable Sheets API, share the dedicated spreadsheet with the service account, and verify its scopes. Do not log credential files.
- Telegram errors: verify bot/chat access securely. Do not log HTTP request URLs, which contain tokens. Failed delivery does not write a receipt.
- n8n connection refused: its container localhost is not the host or assistant. Use an existing shared user-defined network or an address already reachable from n8n. Do not change existing containers automatically.
- SQLite permission error: check volume ownership for container UID 10001; do not recursively change unrelated volumes.
- Email disabled: expected default. No real delivery is needed for development readiness. delivery_unknown/sending requires manual reconciliation, not blind retry.
- Sheets empty after partial failure: SQLite remains authoritative; correct credentials/network and rerun sync.

## Roadmap

Provider-backed public search with official-source verification; Arabic-aware extraction and human review UI; cross-source alias deduplication; sheet-to-local status import with conflict policy; expiring/retracted opportunity states; migrations; stronger per-user approval audits; provider outbox reconciliation; more source adapters and pagination. Keep these explicit rather than presenting them as delivered functionality.
