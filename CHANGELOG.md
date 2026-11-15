# Changelog

## 0.3.0 — 2026-11-15

- Made credential-free public_sources/Wikidata/Wikimedia/Overpass discovery the default; Brave now requires explicit enablement, configuration and credentials.
- Kept hosted AI off by default even when old keys exist; added bilingual local relevance and Arabic location/sector aliases.
- Added published directory archive and community internship table adapters, RSS/Atom parsing/discovery, and official-linked Greenhouse/Lever anonymous read APIs.
- Added safe archive/XML/YAML handling, in-run caching, per-language cursors, source statistics and a read-only free-source-check command.
- Integrated attributed unverified leads with existing tracking/Sheets/Telegram; protected stronger verification from lower-trust imports. Email defaults remain disabled.
- Live public GitHub snapshots parsed 876 company profiles / 1,450 internship rows; strict local filters yielded zero. Other probed public APIs/feeds were blocked by environment egress. No invented local results or live application sends.
- Added zero-cost strategy, source expansion and live-validation documentation, plus automated free-source tests.

## 0.2.0 — 2026-11-15

- Extended the existing service with official Brave Search and credential-free Wikidata directory adapters; configurable sector/location/technical internship queries and priority targets.
- Added durable candidate/query/run state, bounded pagination and crawling, incremental refresh, retries, backoff and sanitized provider reports.
- Added automatic official/career/contact link discovery, structured JobPosting extraction and explicitly uncertain HTML announcements. Preserved COOP and company outreach targets without vacancies.
- Added public-contact evidence, website ownership labels, actual location vs query hints, and unknown-by-default summer eligibility.
- Added cross-source opportunity aliases, company URL deduplication, provenance and new-cohort separation while preserving existing tracking IDs/statuses.
- Integrated discovered records with AI analysis, Google Sheets candidate/company-method tabs, bounded deduplicated Telegram company alerts, and configurable repository n8n schedules.
- Added discovery tests and provider/extension documentation. Email defaults remain disabled; no existing external containers/workflows were changed.
- Live search/provider/site access remains separately credential/network dependent; see docs/VALIDATION.md.

## 0.1.0 — 2026-11-15

- Created a modular Python/FastAPI assistant with isolated demo/live SQLite stores.
- Added configured official-page discovery, evidence-checked monitoring, conservative robots handling, retries, and relevance recommendations.
- Added status/follow-up tracking, deduplicated Telegram notifications, and dedicated Google Sheets mirrors.
- Added disabled-by-default application drafts, explicit approval, daily limits, PDF attachments, and uncertain-delivery guards.
- Added Docker Compose that leaves existing n8n untouched and four inactive importable orchestration workflows.
- Added synthetic demo, automated tests, API documentation, installation and maintenance guides.

Docker build and non-root demo HTTP smoke passed. Live sources/providers and n8n import require their own validation. See DEVELOPMENT.md for future scope.
