# Validation records

## 0.3.0 — 2026-11-15

- **72 automated tests passed**, including the original suite and zero-cost defaults, source contracts, bilingual filtering, free inventory cursor expansion, attribution, safer imports, compressed/streamed data, and read-only diagnostics. No paid keys were needed.
- Locked dependency installation, Python compilation and Docker Compose configuration validation passed.
- Live anonymous source collection/parsing: Remote In Tech GitHub archive HTTP 200, 876 profiles; Pitt CSC & Simplify public GitHub list HTTP 200, 1,450 internship rows initially (1,449 on the later CLI read). Strict local matches: 0 for both. A separate replay with worldwide scope enabled found 466 unverified company leads; not local-office/eligibility evidence.
- A complete default free-profile `internships discover` run in a separate validation database completed with an explicit partial report: both public GitHub sources parsed successfully; restricted API/DNS paths failed; zero local opportunities were invented or marked verified.
- The actual `DEMO_MODE=false internships free-source-check` CLI completed against both live public sources, returned success/parse counts/zero matches and performed no imports or messaging.
- Managed egress denied Wikimedia, Overpass, Greenhouse, Lever and the public RSS probe (CONNECT 403). Those adapters are fixture-tested; successful live API/feed results are not claimed.
- Existing Wikidata/source-DNS limitations remain. No Saudi internship was verified live here. No real email/message was sent, and no existing Docker container/deployed workflow was modified.
- See FREE_DISCOVERY.md for source URLs, counts, extension instructions and zero-cost account/network requirements.

## 0.2.0 — 2026-11-15

- **48 automated tests passed**, including the original suite, API provider contracts with MockTransport, incremental state/TTL/backoff, missing-key fallback, automatic company/job extraction, website ownership uncertainty, shared-ATS mismatches, cross-source/new-cohort aliases, migration preservation, per-source timestamps, corroboration upgrades, ambiguous identifier reuse, Sheets export contracts, and bounded company-alert deduplication.
- A real discovery CLI run in a separate ignored validation database completed with an explicit partial report, zero verified pages and zero invented vacancies. Brave reported missing BRAVE_SEARCH_API_KEY; Wikidata transport was unavailable; source DNS checks failed.
- A direct HTTPS Wikidata probe returned CONNECT denied (403) from the managed outbound proxy. This environment does not grant query.wikidata.org access. No bypass was attempted.
- Live Brave search, Wikidata results, official-site parsing against current internet pages, Google/Telegram delivery and n8n import/execution remain unverified. Google Sheets export was tested with a mocked authorized session, not live credentials.
- Python compile checks, Docker Compose configuration validation and repeatable repository workflow generation passed. The existing Docker deployment was not changed.
- No real application email or notification was sent. No existing Docker container or deployed n8n workflow was modified.

## 0.1.0 — 2026-11-15

Validated in the development cloud instance using Python 3.12:

- Installation from requirements.lock, editable project installation: passed.
- Automated suite: **14 passed**. Source HTML, SMTP delivery, and transport failures are mocked; no real application email was sent.
- CLI demo import and Telegram preview: passed with two explicitly synthetic records.
- Running Python HTTP server: health, authenticated monitoring, listing, and daily notification preview passed.
- Docker Compose configuration validation: passed with the local example environment file.
- Docker build: passed using the managed host's trusted combined CA as a BuildKit secret, with TLS verification enabled. Initial missing trust and demo-file permissions were corrected.
- Non-root Docker HTTP smoke: health, demo import, listing, new notification preview, and non-writing Sheets preview all passed. Source configuration files were readable.
- Four workflow files: JSON parsing, inactive default, and absence of send actions checked by tests. Actual n8n import/execution remains unverified; no existing n8n container is present in this instance.

Not validated: live source availability/terms, real vacancy correctness, Google Sheets credentials/writes, Telegram delivery, AI-provider calls, SMTP delivery, and restoration in another cloud task. Live integrations require operator configuration and explicit validation. At 0.1, broad public search was future scope; 0.2 adds the search/verification pipeline described above. Seeds are not advertised internships.

Known non-failing warning: the selected Starlette release emits a deprecation warning for its httpx TestClient backend. All tests execute and pass.
