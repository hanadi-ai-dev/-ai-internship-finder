# Development and continuation guide

## Local loop

Work in this checkout. Do not edit the older `internship-finder` project or any existing containers/workflows. Read README, SETUP, and ARCHITECTURE first. Python 3.12 was used for validation. Install `pip install -e '.[dev]'`; run `pytest -q`. Reproduce the development environment using `pip install -r requirements.lock` and `pip install --no-deps -e .`. Lockfile includes development test dependencies; refresh deliberately after verifying tests. It is a platform-specific tested environment snapshot rather than a cross-platform hash lock.

`internships demo` imports synthetic fixtures idempotently; `internships notify` previews alerts in demo. Never enable live email to run tests. API tests exercise authorization, demo ingestion, statuses, exports, and guarded applications. Source tests use controlled HTML, not fragile internet fixtures. No test contacts Telegram, Google, AI providers, or SMTP. Docker and live integrations require separate validation; passing unit tests does not establish their access.

## Adding organizations and opportunities

Edit `config/sources.json`, preserving explicit public source URLs and cities. Include startups, SMEs, banks, hospitals, research/government organizations, and any relevant technical departments. `priority` controls human review priority; it does not remove lower-priority targets. Add reviewed opportunity selectors as described in SETUP. Broad discovery now uses free public sources, Wikimedia/Wikidata and bounded OpenStreetMap inventories, incrementally follows relevant official career/contact links, and extracts structured internships or explicitly uncertain announcements. Reviewed source selectors remain supported. Provider settings, query coverage, safeguards, budgets and extension interfaces are documented in [docs/DISCOVERY.md](docs/DISCOVERY.md). Keep unverified targets distinct from opportunities. Do not commit personal contact data; institutional publicly listed emails only.

To add an adapter, extend sources.py behind the same fetcher policies and core.validate schema. Test title changes, absent selectors, blocked robots, missing dates, ambiguous eligibility, pagination, duplicate URLs, and disappearance. Never treat a score or COOP label as eligibility evidence. Avoid broad exception swallowing without reporting per-source errors.

To change data structures, add a migration path and backups before modifying tables. Keep stable IDs or explicitly migrate relationships. Notification fingerprints should exclude observation timestamps. Keep AI outputs advisory and validate JSON. Source text can contain prompt injection; do not give models tool access or secrets. Configured source URLs and AI endpoints are trusted operator settings, not arbitrary anonymous input.

## Workflows

`python docs/generate_workflows.py` regenerates the four inactive n8n workflow files using schedules/timezone in config/discovery.json. It never edits deployed workflows. Discovery runs every four hours by default, and syncs the discovery/company results to Sheets. Credentials are intentionally absent; select Header Auth after importing. Community Edition compatibility avoids paid Variables and uses literal editable API URLs. No workflow deploys itself or sends email. When changing workflow node versions, test imports against the target n8n release before claiming compatibility. For unattended error alerts, configure your existing n8n error-workflow policy manually after review; API/source failures are otherwise visible in executions and returned error arrays.

## Environment variables

See `.env.example` for every setting. API_TOKEN protects action routes. DEMO_MODE selects isolated state and prohibits external notifications/SMTP; DATA_DIR controls SQLite paths. SOURCE_CONFIG selects reviewed JSON. TELEGRAM_BOT_TOKEN/CHAT_ID and GOOGLE_SHEET_ID/GOOGLE_APPLICATION_CREDENTIALS are live integration settings. AI_BASE_URL/KEY/MODEL enable optional advisory classification. EMAIL_SENDING_ENABLED, EMAIL_AUTO_APPROVED, EMAIL_DAILY_LIMIT and SMTP_*/CV_PATH/TRAINING_LETTER_PATH are future opt-in sending controls. ASSISTANT_PORT changes host publishing; N8N_NETWORK is required only for the optional external-network Compose override.

Restart only the assistant service after changing its env_file; other containers are outside this project's scope. Shell CLI does not automatically load `.env`; use exported variables, or the service through Compose. Google auth uses a credential file/ADC, not invented API tokens. Some managed environments cannot mount raw secrets or allow SMTP; report this rather than bypassing network policy.

## Troubleshooting

- 401: API_TOKEN must be set in the service and match the request Header Auth credential.
- Missing live listings: inspect /discovery/status, per-provider errors, the candidate queue, and /monitor errors. Run free-source-check and inspect the free provider/source status; confirm network grants and public DNS. No seed or snippet creates a fake vacancy. Reviewed blocks remain an optional override. Robots restrictions, JavaScript-only pages and selector changes require source review.
- Google 403: enable Sheets API, share the dedicated spreadsheet with the service account, and verify its scopes. Do not log credential files.
- Telegram errors: verify bot/chat access securely. Do not log HTTP request URLs, which contain tokens. Failed delivery does not write a receipt.
- n8n connection refused: its container localhost is not the host or assistant. Use an existing shared user-defined network or an address already reachable from n8n. Do not change existing containers automatically.
- SQLite permission error: check volume ownership for container UID 10001; do not recursively change unrelated volumes.
- Email disabled: expected default. No real delivery is needed for development readiness. delivery_unknown/sending requires manual reconciliation, not blind retry.
- Sheets empty after partial failure: SQLite remains authoritative; correct credentials/network and rerun sync.

## Roadmap

Additional official directory/search adapters; broader Arabic extraction and a human review UI; stronger ambiguous-duplicate reconciliation; sheet-to-local status import with conflict policy; expiring/retracted opportunity states; migrations; stronger per-user approval audits; provider outbox reconciliation; more source adapters and pagination. Keep these explicit rather than presenting them as delivered functionality.

## Discovery development

Read docs/DISCOVERY.md before changing search or extraction. tests/test_discovery.py uses httpx.MockTransport, explicit fixture HTML and SQLite temporary databases to cover provider contracts, query coverage, incremental pagination/TTLs, missing-key fallback, evidence extraction, shared ATS mismatches, ownership uncertainty, deduplication/new cohorts, backoff, robots/redirect/response-size limits, and notification stability. Tests never contact providers or send real messages/applications. DISCOVERY_CONFIG, BRAVE_SEARCH_API_KEY and COMPANY_ALERTS_PER_RUN are documented in .env.example. Investigate live provider/network errors separately from passing offline tests.

## Extending free discovery (0.3)

Start with docs/FREE_DISCOVERY.md and tests/test_free_sources.py. Add a documented anonymous API or a legitimately published/licensed feed/directory, not search-engine HTML or an assumed free trial. PublicSources supports GitHub directory archives, community internship tables and RSS/Atom. Keep attribution and source statistics; stage missing/uncertain facts as Unknown. New adapters must preserve API-only read operations, robots checks for feeds/sites, public-network checks, size limits, incremental cursors and tests for source-schema changes. Archived files are never extracted to disk; use yaml.safe_load only.

Use `DEMO_MODE=false internships free-source-check` for read-only current source validation. Tests use fixtures and MockTransport; live source counts are documented separately and may change. No test may call a paid provider, send a real message/email, require billing, or edit external workflows/containers. Test that old Brave/AI credentials do not activate paid services by default. An optional new provider must not become necessary for the free profile. Store raw snapshots/validation DBs only under ignored data/.

## Extraction and reliability (0.4)

Use tests/test_announcements.py for bilingual cards/tables, source-scoped methods/dates, ordinary jobs vs internships, programs/closed opportunities, cross-source tracking, shared ATS identity, LinkedIn manual leads, network codes/retries and priority diagnostics. Keep role evidence shared across structured HTML and free ATS/feed adapters. Never infer an application method from a detail URL or a raw API reference. Add new layout selectors with negative fixtures so broad containers cannot mix multiple jobs. Local eligibility stays Unknown unless reviewed evidence supports another value.

LinkedIn guards apply at both Fetcher and APITransport: no LinkedIn/lnkd.in request, login, robots probing, redirect-follow or personal-account automation is permitted. Metadata capture/import is a lead, never official verification. Keep observed-only timestamps distinct from fetched/verified timestamps; reject conflicting employer identity and do not inherit trust from third-party associations.

The Windows update helper is delivered for user review/execution, not run by development. It must preserve existing project name and original Compose overrides/volumes and use --no-deps with only assistant. Never substitute docker compose down, prune, -v, or a guessed project name. See docs/WINDOWS_UPDATE.md and docs/EXTRACTION_AND_LINKEDIN.md.
