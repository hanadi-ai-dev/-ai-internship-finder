# Automated discovery (0.3)

The default profile is now completely credential-free discovery with local bilingual analysis. Read [FREE_DISCOVERY.md](FREE_DISCOVERY.md) for the free strategy, current adapters and actual live-check results. Optional paid integrations are not required.

This extends the original application; it does not replace the tracked database or require another service. Every discovery run searches configured providers, stages candidate URLs, then verifies a bounded set of due pages. No email action is part of discovery. All demo runs remain offline.

## Providers and safe fallback

| Provider | What it does | Credentials and limitations |
| --- | --- | --- |
| Brave Web Search API (optional; disabled by default) | Searches official public API for company/sector/location queries and Summer/COOP/research/general technical internship queries, including Arabic terms | `BRAVE_SEARCH_API_KEY`; check current plan/pricing/quota. Key absent → explicit `missing_credentials`, no simulated search results |
| Wikimedia search + entity lookup | Anonymous English/Arabic article search and Wikidata website properties | No account, billing or key; bounded queries and separate language cursors |
| Public sources | Published directory/company archives, community internship lists and RSS/Atom; employer-linked Greenhouse/Lever read APIs | No account, billing or key. Third-party assertions stay unverified; see FREE_DISCOVERY.md |
| Wikidata Query Service | Credential-free CC0 organization directory: organizations with a listed website and headquarters/administrative location in configured cities | No key. Sparse and community-maintained; not a full web index or vacancy search. Website association is a Wikidata claim until independently reviewed |
| Configured/reviewed sources | Priority/manual targets in `config/sources.json` and the existing explicit opportunity monitor | Useful supplement when providers are unavailable. Never presented as a successful broad search |

References: [Brave API documentation](https://api-dashboard.search.brave.com/documentation), [Wikidata Query Service](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service), [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access). Quotas, free access and terms can change; no pricing promise is made. No Google search HTML, CAPTCHA bypass, login scraping, or search engine page scraping is used. Known search-result HTML hosts are rejected by the discovery queue.

Wikidata queries resolve configured English city labels rather than maintaining a hardcoded organization list. They include subclasses of organization with `official website` and location/headquarters properties. This can surface banks, hospitals, government, research organizations and many other sectors. Missing Wikidata entries and branch-only offices are common; enable broad web search and add authoritative sources to improve coverage. Discovering an organization does not establish that it has an AI/IT department; `technical_department` stays Unknown until researched. Never drop an employer for lacking advertised vacancies.

## Setup and commands

1. Keep `EMAIL_SENDING_ENABLED=false` and `EMAIL_AUTO_APPROVED=false`.
2. Review `config/discovery.json`; free defaults are public_sources, wikidata, wikimedia and overpass. Keep ENABLE_BRAVE_SEARCH=false and AI_PROVIDER=local. Do not put any optional credentials in JSON or commit .env.
3. Ensure egress permits the configured free API/directory hosts (see FREE_DISCOVERY.md) and the official/linked domains selected for collection. Restricted environments need per-host grants; a search API grant does not allow arbitrary result sites. Local Python DNS must resolve public source domains for SSRF validation; HTTP proxy-only DNS does not satisfy that check. Use a normal DNS-capable runtime or infrastructure-supported public DNS resolution rather than disabling validation.
4. Export variables for CLI (CLI does not read `.env`), or restart only your assistant Compose service after editing its env_file. Never change existing n8n containers.

```bash
# The following calls perform public-source research, never application sending.
DEMO_MODE=false .venv/bin/internships discover
DEMO_MODE=false .venv/bin/internships discovery-status
DEMO_MODE=false .venv/bin/internships discovery-candidates
DEMO_MODE=false .venv/bin/internships monitor
```

Equivalent authenticated API: `POST /discover`, `GET /discovery/status`, `GET /discovery/candidates?limit=100`, `POST /monitor`. Candidate limit is 1..1000. `GET /companies` includes outreach targets. A run report includes provider request/hit/status counters, pages fetched vs pages verified, company/opportunity upserts, errors, queue states, and budget exhaustion. Inspect these rather than treating HTTP 200 as proof of live success. Provider/parse failures preserve existing data. Candidate `error`/`needs_review` states are visible in both API and Sheets. `last_attempt` never substitutes for `verified_at`.

`status: partial` means a provider is unavailable or a source failed. Brave is absent from the default providers and never needs credentials in free mode. Explicitly enabling it is outside that profile. Missing optional credentials never block independent free collection. An empty result can be legitimate and is never filled with demo data. When public APIs are unavailable, independently reachable directory snapshots, feeds and targets may still refresh; reports distinguish these successes from blocked API searches. If there is no network at all, the report records errors and no page verification timestamps.

## Configuration reference

`DISCOVERY_CONFIG` selects the JSON file (default `config/discovery.json`). Existing `SOURCE_CONFIG` still selects reviewed targets/selectors. Configuration is read on each run. Search and refresh settings:

| Setting | Behavior |
| --- | --- |
| providers | Default public_sources, wikidata, wikimedia, overpass; optional brave additionally needs explicit ENABLE_BRAVE_SEARCH=true. [] runs only the configured frontier |
| free_sources | Published github_directory, internship_table or feed source descriptors; name, kind, HTTPS URL, attribution_url and enabled |
| languages / location_aliases | English/Arabic queries and geographic matches, including Jeddah/Jidda/جدة, Riyadh/الرياض, Thuwal/ثول/KAUST |
| include_remote_leads | false by default; opt-in to explicit worldwide leads without claiming Saudi eligibility |
| city_bounds | Approximate Overpass inventory boxes in south/west/north/east order; bounded area, claims unverified |
| locations | English city labels and search locations; defaults Jeddah, Riyadh, Thuwal |
| sectors | Broad company search terms across startups, SMEs, corporations, government, banks, hospitals, research, universities, retail, logistics, energy, telecom; extend freely |
| fields | Technical search terms; defaults AI, Data Science, ML, Software, IT, Cybersecurity |
| internship_terms | Summer, COOP, research, unspecified internships, Arabic summer/COOP terms |
| priority_targets | First free Wikimedia and optional Brave queries; initial organizations remain configured research targets |
| extra_queries | Additional public search queries, e.g. Arabic sector terms or authoritative directories |
| search_requests_per_run | Logical provider query budget across all providers; default 6, max 50. Wikimedia may make two HTTP reads per query; rate limits apply to each read |
| results_per_page / max_pages_per_query | Results per request and bounded API pagination; default 10/3 for web searches; Brave offsets limited to 0..9. Free inventories retain cursors until exhausted |
| search_refresh_hours | Completed query TTL (24h); unfinished pagination rotates fairly with other tasks |
| provider_interval_seconds | Per-provider minimum request spacing; default 2s, minimum 1s |
| pages_per_run / links_per_page / max_depth | Frontier page, fanout and crawl-depth budgets; defaults 12/12/3 |
| max_candidates | Persistent frontier cap (10,000); existing candidates continue refreshing at cap |
| page_refresh_hours | Successful/needs-review page refresh TTL (24h) |
| error_retry_hours | Initial failed-page retry delay (6h), exponential up to one week |
| max_errors_per_run | Stops frontier processing after this many source errors (20) |
| run_budget_seconds | Soft elapsed-time budget (120s); checked before each new task/page; an in-flight request/retry can exceed it |
| schedules | Timezone and n8n discovery, monitor, notifications cron expressions |

Search queries rotate through priority targets, interleaved company/internship queries, and extra queries. A small per-run budget intentionally spreads a large query matrix over multiple scheduled runs; it does not claim to search every combination on the first run. Durable query states preserve last attempt/success, page offset, next due time, and errors across restarts. Query text changes create fresh tasks. Failed queries have a cooldown; failed pages have exponential backoff. Candidate cap and crawl budgets protect against unbounded site expansion. Source robots delays greater than 60 seconds are deferred as explicit errors to keep this synchronous worker bounded.

Edit `schedules` and run `python docs/generate_workflows.py` to regenerate only repository JSON. Default discovery: every four hours; monitoring 07:00 and notifications 08:00, Asia/Riyadh. After review, manually reimport/replace the intended workflows and select Header Auth credentials in your n8n UI. No code edits deployed workflows or containers. HTTP node timeouts allow bounded discovery runs. Python does not run an internal scheduler. For frequent alerts, change notification cron separately. `COMPANY_ALERTS_PER_RUN` defaults to 10 (0 disables company alerts); extra unsent companies remain for future runs.

## Website verification and evidence

- Search titles/snippets are provenance leads, never evidence for an email, date, vacancy, or city.
- Configured priority targets are not automatically certified official. Independently verified source targets marked `"reviewed": true` and Wikidata-asserted website associations are recognized separately. Wikidata is not an independent guarantee of current website ownership.
- Search-only sites can self-identify via public Organization JSON-LD. They remain `self_identified` / ownership unconfirmed. Pages without an organization association stay `needs_review`; employer URLs explicitly present in JSON-LD may seed new candidate websites.
- To approve an uncertain company, independently verify it and add its name, city and canonical website with `"reviewed": true` to `config/sources.json`. The next discovery run promotes that target's authority to `reviewed` and queues it promptly.
- Crawl only relevant career/internship/contact/about links with depth/fanout bounds. External recruiting portals must be linked from the employer's site; a structured job on a shared portal also needs matching hiringOrganization name/website. Mismatched employers remain review candidates, not that company's internships or recruitment contacts.
- Each redirect target undergoes HTTPS, public-IP and robots checks; login/private addresses are rejected. A robots 404 means no robots policy; 401/403/unavailable robots stops collection. A redirecting robots URL requires a canonical source correction. Terms are an operator responsibility: do not add sites forbidding automation. No JavaScript/browser bypass is implemented.

Verified timestamps mean content was fetched from that source; they do not certify every organizational fact. Query location hints and actual `jobLocation` are separate. Unknown or other locations stay visible, with `location_match` true/false/null; lower relevance never deletes a result.

## Opportunity extraction and application methods

JSON-LD `JobPosting` is parsed from arrays, nested graphs and objects. Explicit title/description/employmentType must mention an internship/COOP/training term. Records retain original source URL, structured job identifier, description, published date, location, and ISO `validThrough` deadline when present. `datePosted` is **not** assumed to be the application opening date. Invalid/ambiguous dates remain blank. The original structured date evidence is retained.

A specific internship H1 and a visible application link support an HTML announcement fallback. Such records explicitly say **availability unconfirmed**; generic careers/internship program mentions without an application action remain leads. Pages can advertise expired or recurring programs; the system does not label them currently open. COOP stays eligible for review and summer eligibility stays Unknown until a human supplies verified evidence through the original reviewed-selector mechanism. No AI-derived eligibility or guessed deadlines/emails are permitted.

Public mailto and JSON-LD email addresses are retained with source, check time and context. They are general contacts unless explicit nearby recruitment/application wording is present on a recognized official/linked source. A mailbox named `careers` alone is insufficient. Unconfirmed website ownership keeps emails general, so automated application drafting cannot treat them as verified recruitment contacts. Unobfuscated plain-text emails without a mailto/structured email are currently not extracted; no addresses are synthesized. Explicit apply/form links are manual methods; no web forms are submitted.

## Deduplication and data safety

The migration is additive: new frontier, query-state, run-report and opportunity-alias tables. Existing opportunity IDs, statuses, follow-ups, applications and notification receipts remain. Back up the live SQLite database before upgrading. Company identities normalize HTTPS, www, trailing slash, tracking parameters, and query order; provenance is merged rather than lost. Distinct company URL paths remain separate, but same-host search association uses the known employer; shared hosting identities may require manual correction.

Opportunity alias matching uses employer website (or legacy normalized name), exact normalized title/location, canonical source/application URLs, and employer-scoped structured job identifiers. Stable aliases merge official/ATS copies; statuses and follow-ups survive. Explicit new posting years create separate cohorts so last year's application does not block a new one. Different vacancies, renamed titles, missing identifiers, different locations and ambiguous shared application forms are not fuzzily merged. There is no claim of perfect cross-source recall. Same-title recurring roles lacking a stable ID/date still need review. Multiple sources and per-source check timestamps are retained in candidate provenance/source_urls/source_verifications; only actually fetched page URLs are recorded as verification sources. The first tracked source remains the primary URL.

Notification fingerprints omit verification timestamps, source-list growth, tracking status/follow-up changes and advisory AI score changes. Source refreshes therefore do not repeatedly announce unchanged listings. Company alerts deduplicate on identity, career links and contact addresses and explicitly say internship availability is unknown. Daily summaries still use the existing opportunity notification behavior. Google Sheets includes expanded verification/recommendation fields plus `CompanyMethods` and `DiscoveryCandidates`; its dedicated tabs remain replaceable mirrors, not an approval channel. AI failures retain the listing and report unavailable advisory analysis instead of losing evidence.

## Adding a provider or extractor

Implement `name`, `available`, and `search(task, page, count) -> (hits, more)` like `BraveSearch`/`WikidataSearch`. Use the shared APITransport for retries/rate limits and sanitized errors. Hits contain public URL, title, provider, query/location hint, and `authority: unverified` by default. Only explicit independently sourced website properties should use a stronger claim label; do not mark every search result official. Register the provider in `run_discovery` and config validation, extend `query_tasks`, document keys/endpoints/terms/quota, and add MockTransport contract tests and failure tests.

For source adapters, keep Fetcher's public HTTPS/robots limits, attach exact evidence, and stage uncertain results. Test ambiguous dates, missing job identifiers, shared ATS mismatches, cross-source aliases, new cohorts, duplicate notifications, source removal, redirects, missing credentials, backoff, and persistence. Preserve email-disabled defaults and never invoke real SMTP in development. For authenticated/JavaScript-only pages, report a limitation or use an official documented API; do not work around access controls.

Free RSS/Atom, community table, directory archive and employer-board ingestion are detailed in FREE_DISCOVERY.md. Community/feed publication is evidence of an unverified lead, not official verification. Existing stronger evidence/statuses cannot be downgraded by these imports. Use `internships free-source-check` for read-only live source diagnostics; no local vacancy is implied by a successful source download.
