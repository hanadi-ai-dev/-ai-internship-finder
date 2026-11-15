# Architecture and contracts

## Services and flow

The existing n8n instance is an external orchestrator, not managed by Compose. Four independent importable workflows handle company discovery, internship monitoring/Sheets export, notifications, and manual application review. Python is one FastAPI process using a serialized action lock; SQLite WAL stores state. Docker runs one non-root service on port 8000 internally and 8018 on host loopback. Do not run multiple API workers against the shared connection model; scale by introducing a durable queue before horizontal replication.

`search.py` implements official Brave and Wikidata API adapters with rate limits and retry handling. `discovery_store.py` persists candidates, query cursors, TTL/backoff and run reports; `discovery.py` orchestrates incremental search and verification. `extraction.py` parses structured organization/job evidence and guarded announcements. `core.py` validates data and owns SQLite persistence. `sources.py` checks public HTTPS/robots, fetches configured official pages, finds career links/general contact mailtos, and verifies explicitly mapped vacancy evidence. `integrations.py` scores relevance locally or with optional AI, exports Sheets, and sends Telegram. `applications.py` owns the separate opt-in SMTP lifecycle. `api.py` provides authenticated operations, and `cli.py` provides manual/demo commands.

## Data and verification

Companies: stable source URL identity, name, city, sector, priority, career links, general contacts, verification status and check time. Organizations need no advertised vacancy to be retained. Discovery uses configurable API queries across sectors, locations and technical internship terms, plus priority/manual targets. Search results enter a verification frontier. Wikidata is a limited credential-free organization directory; Brave requires a key. Initial research targets and search snippets are not vacancy evidence. A successful page fetch verifies source access, not every factual claim about an organization.

Opportunities: stable ID, company/title/city, Summer/COOP/research/unspecified kind, eligibility, quoted evidence, dates, requirements, application method, source, timestamp, advisory relevance, status and follow-up. A classification other than Unknown needs evidence; neither COOP nor a low score excludes a record. For manual mappings, date and email values must occur in the configured source block. Automatic extraction retains explicit structured dates, title/description, source links and contact context; dates and eligibility are never guessed. Email-kind and eligibility classifications depend on reviewed configuration. Source links alone cannot prove the semantic correctness of that review. Absent data stays blank/Unknown.

Upserts preserve legacy IDs and use an additive alias index across normalized employer/title/location, official/application/canonical job URLs and employer-scoped structured IDs. Explicit new posting years remain separate cohorts. Tracking survives merged sources. URL normalization removes known tracking parameters, fragments and www/trailing-slash differences while retaining job identifiers. Ambiguous duplicates need manual review. Demo/live databases are separate files, and demo records and messages are labeled. Live fetches never import synthetic data.

SQLite is the source of truth; Sheets tabs are replaceable mirrors. Status values: Not Applied, Applied, Waiting, Interview, Accepted, Rejected. Tracking mutations use the authenticated API. Drafts and application logs are local sensitive state; backups and retention are the operator's responsibility. No personal student profile is shipped.

## Failure behavior and delivery

Source failures produce structured per-source errors and preserve existing records. HTTP 429/5xx source responses are retried up to three times with capped delay; no TLS bypass or credentials extraction. Redirect destinations receive fresh public HTTPS and robots checks; a redirecting robots endpoint itself requires canonical-source review. Unavailable robots stops collection; 404 means absent robots. Responses are stream-bounded to 2 MB. Sources must be operator-approved public hosts, with terms checked outside the crawler. IPv4/IPv6 private destinations are rejected; DNS rebinding and hostile proxy environments still require infrastructure egress restrictions.

New alerts use stable content fingerprints excluding check timestamps. Daily/deadline alerts use Saudi dates; sent receipts are committed only after successful delivery. Delivery is at-least-once across crashes: Telegram and SQLite have no shared transaction. Credentials and token-bearing URLs are omitted from API integration errors. Google sync is idempotent for fixed SQLite state but not transactionally atomic across clear/write requests; rerun after partial failures.

Application lifecycle: draft → approved → sending → sent or delivery_unknown. Default guards prohibit all demo sends and require explicit live enablement. A transaction claims a unique application and checks the daily limit before SMTP. Attachments and configuration are validated before claiming. A sending/uncertain record blocks automatic retries; manually reconcile before any administrative change. A crash after the SMTP handoff can leave `sending`; this is intentionally treated as uncertain. No application send action is present in n8n. Pre-approved mode is an explicit operator switch, never inferred from a sheet or source text.

## API

`GET /health` is public. All other operations require `Authorization: Bearer API_TOKEN`; an unset token denies access. `/docs` exposes schemas, not data. Validation errors use 400/422; provider failures use a sanitized 502. Automation must inspect per-source error lists, not just HTTP status.

| Route | Purpose |
| --- | --- |
| GET /companies, /opportunities, /applications | Read tracked records |
| POST /discover | Search APIs and incrementally verify candidate/company/internship pages (demo skips network) |
| GET /discovery/status, /discovery/candidates | Inspect provider/run reports, queue, provenance and uncertainty |
| POST /monitor | Verify configured live listings; demo imports synthetic fixtures |
| POST /sync | Export dedicated Sheets tabs (demo never writes) |
| POST /notify/new, /notify/daily, /notify/deadlines | Deliver deduplicated messages (demo returns previews) |
| PATCH /opportunities/{id} | Set status and optional ISO follow_up |
| GET /opportunities/{id}/recommendation | Advisory relevance and category |
| POST /applications/draft | opportunity_id and applicant_summary JSON |
| POST /applications/{id}/approve | Explicitly approve existing draft |
| POST /applications/{id}/send | Guarded future SMTP operation |

## Extension boundaries

Add source adapters with provenance-first structured results, never generate missing contacts/deadlines with a model. Additional public search adapters must retain candidates separately until verification, observe provider terms, and not bypass robots. Implement the provider contract in docs/DISCOVERY.md. Add migrations before changing persistent schemas. Add scoped operator credentials/audit identities before multi-user deployment. An SMTP/API outbox and provider message identifiers would improve uncertain-delivery reconciliation. Web form submission is intentionally unsupported.

The broad discovery pipeline, trust labels, query/refresh budgets, alias rules and extension contracts are specified in [docs/DISCOVERY.md](docs/DISCOVERY.md). Website association from Wikidata is an external claim; configured seeds and self-identified search sites remain unconfirmed unless independently reviewed. Use reviewed=true only after that review. External shared ATS jobs need employer matching. SQLite migrations add discovery state and opportunity aliases without rewriting tracked IDs. AI failure cannot discard a verified discovery record.
