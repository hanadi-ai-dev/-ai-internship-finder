# Zero-cost discovery strategy (0.3)

The default workflow requires **no paid subscription, credit card, billing account, search API key, or hosted AI service**. Run Python/SQLite and optional n8n Community Edition with Docker Engine on an existing computer. Local bilingual relevance analysis is enabled by default. Google Sheets and Telegram are optional free integrations with their own free-account credentials; SQLite, discovery and tracking do not depend on either.

This is a software/service requirement, not a promise that a computer, electricity, internet, or an optional cloud host costs nothing. No cloud host, paid Docker Desktop license, Simplify account/extension, Brave plan, or OpenAI account is required.

## Sources and expansion layers

| Layer | Mechanism | Trust and coverage |
| --- | --- | --- |
| OpenStreetMap / Overpass | Anonymous bounded city inventory of offices, banks, hospitals, universities, industrial and retail organizations with published website tags | All-sector local leads with ODbL attribution; bounds are approximate, and website/address/technical-department claims remain unverified |
| Wikidata | Anonymous SPARQL query for organizations with listed websites and headquarters/location in Jeddah, Riyadh, Thuwal | All organization sectors, but community data is incomplete; website association remains an external claim |
| Wikipedia + Wikidata | Documented anonymous English/Arabic MediaWiki search, followed by batched entity website claims | Free search for priority organizations and sector/location combinations; not a general web index; city in a query is only a hint |
| Remote In Tech | Published ISC-licensed GitHub source archive; parse changing company profiles and career URLs | Automatically discovers new company leads without hardcoded company names; mainly remote technical firms, not a Saudi company census |
| Pitt CSC & Simplify community internship list | Public GitHub README tables; original application URLs and publisher attribution retained | Supplemental internship leads, primarily outside Saudi Arabia; community assertions never become official verification |
| Employer sites | Existing robots-aware HTTPS career/contact/structured JobPosting collection | New official-linked pages and organizations discovered incrementally; configured seed domains stay uncertain until corroborated/reviewed |
| Public RSS/Atom | Add any permitted published feed to free_sources; discover employer feed links from HTML automatically | Arabic/English internship/location filtering; unknown employer/dates remain unknown |
| Greenhouse / Lever | Documented read-only public job-board APIs; infer board slug only from a published career URL | No API key/account/billing. Official employer referral is required before calling a result official-linked; a directory's claim alone is insufficient |

Default provider names in `config/discovery.json` are `public_sources`, `wikidata`, `wikimedia`, and `overpass`. Brave is not enabled. Its adapter additionally requires `ENABLE_BRAVE_SEARCH=true`, its name in providers, and a key; this is outside the zero-cost profile. Similarly, remote model calls require `AI_PROVIDER=openai`; even an old AI_API_KEY is ignored by default. `AI_PROVIDER=local` provides deterministic Arabic/English category/score explanations on the existing CPU.

Free coverage expands by adding sectors/Arabic aliases, licensed directories in supported formats, published RSS/Atom feeds, and official employer targets. Site crawling discovers career/ATS/feed links automatically. New jobs from employer boards are fetched without manually mapping every vacancy. No web search HTML is scraped. Do not add a private/authenticated endpoint, repurpose a paid API, or scrape a site whose terms prohibit it.

## Actual live checks on 2026-11-15

| Source | Observed live result | What it establishes |
| --- | --- | --- |
| Remote In Tech public GitHub archive | HTTP 200; **876 company profiles parsed** | Live retrieval and current-format parsing work. Strict Jeddah/Riyadh/Thuwal filters matched **0**. Replaying that live snapshot with explicit worldwide mode produced **466 unverified company leads**, not local office or internship evidence |
| Pitt CSC & Simplify Summer 2027 GitHub list | HTTP 200; **1,450 internship rows parsed** initially (1,449 on the later CLI read) | Live retrieval/table parsing work. Strict local filters matched **0**; no Saudi vacancy was manufactured |
| OpenStreetMap Overpass API | Managed proxy denied CONNECT (403) | Contract, bounded geography, pagination, partial-response rejection and attribution are fixture-tested; no live map inventory result claimed |
| Wikimedia search | Managed proxy denied CONNECT (403) | Adapter fixture tests pass; live public API results were **not** verified here |
| Greenhouse public board API | Managed proxy denied CONNECT (403) | Contract/pagination/ingestion tested with controlled responses; no successful live ATS result claimed |
| Lever public postings API | Managed proxy denied CONNECT (403) | Same limitation; no live job claim |
| Published job RSS probe | Managed proxy denied CONNECT (403) | RSS/Atom parsing, robots-aware document route and discovery tested offline; no successful live feed claim |
| Wikidata SPARQL / official seed websites | Prior live attempt failed through policy/DNS checks in this environment | Existing limitation remains; no new successful verification claimed |

A full default free-profile discovery run also completed: public_sources succeeded, restricted API/DNS paths were reported as failures, and the overall status was partial. **No local vacancy was verified in these checks.** Collection success, a third-party lead, a website association, and an official-source result are distinct. Counts describe the downloaded snapshots, not permanent current totals. Raw snapshots and development databases are ignored and not committed. No messages or applications were sent.

Reproduce a read-only check of the configured free directory/community sources:

```bash
DEMO_MODE=false .venv/bin/internships free-source-check
```

This reports per-source parse statistics and zero matches honestly. It does not import records, contact Telegram/Sheets/AI, or submit applications. Demo mode returns disabled without networking. Normal scheduled ingestion uses `internships discover` / `POST /discover` and then the existing monitoring/sync/notification jobs.

## Geographic and language policy

OpenStreetMap city bounds (south/west/north/east) are configurable in `city_bounds`; they cover approximate Jeddah, Riyadh, and Thuwal/KAUST search areas. Map tags do not certify a legal entity or its address. Default city aliases include Jeddah/Jidda/جدة, Riyadh/الرياض, and Thuwal/ثول/KAUST/كاوست/جامعة الملك عبدالله. Search terms include English and Arabic sectors, AI/data/software/IT/security and Summer/COOP/research/training vocabulary. Wikimedia language cursors are separate so one language cannot accidentally suppress the other. Every sector remains eligible: technical departments are potential, not assumed, until source evidence confirms them.

`include_remote_leads` is **false** by default. Filter changes create fresh source query cursors but do not delete previously tracked leads. If explicitly set true, directory/feed statements of worldwide/anywhere scope may produce additional leads with **Saudi eligibility unverified**. A bare “remote” or “US remote” is not enough. This switch never relocates a foreign company to Jeddah/Riyadh or claims a student can legally work for it. Exact workplace locations from ATS data are kept separately from query hints; ambiguous locations remain Unknown. COOP is retained regardless of label; summer eligibility stays Unknown without reviewed evidence.

## Add a free feed or board

Add a permitted RSS/Atom publication to `free_sources`:

```json
{
  "name": "Reviewed publisher job feed",
  "kind": "feed",
  "url": "https://publisher.example/jobs.rss",
  "attribution_url": "https://publisher.example/",
  "enabled": true
}
```

This is a format example, not a real working source. Replace it with a published allowed feed. XML external entity/DOCTYPE declarations are rejected; URLs are public HTTPS; robots and size/redirect checks apply. Feeds need no assumed employer field: missing employer becomes explicitly “Unknown employer (public feed lead)”. Optionally configure company_name only when the publisher actually identifies that employer. Dates, email addresses and summer eligibility are not guessed from feed ages or prose. All third-party feed results are labeled unverified in tracking, Sheets and Telegram.

For Greenhouse/Lever, add a real employer homepage to existing sources or let a free directory/Wikimedia discover it. The crawler recognizes published `boards.greenhouse.io/<board>`, `job-boards.greenhouse.io/<board>`, and `jobs.lever.co/<board>` (including EU Lever) links, then calls the documented anonymous APIs. It never guesses board slugs. HTML alternate RSS/Atom links are also queued automatically. Only a recognized employer site's actual referral marks the API/feed official-linked. No sending/submission API is called.

Directory and community-source adapters use cached snapshots within a run, bounded per-run work, durable enumeration cursors, refresh TTLs and source statistics. Archive contents are parsed in memory without extraction; compressed/decompressed/file-count limits and safe YAML loading apply. Free inventories continue pagination over future runs until exhausted instead of repeatedly stopping at the first web-search page cap. Existing candidate budgets, retries, backoff, aliases, status preservation and notification deduplication remain. Lower-trust imports add provenance but cannot downgrade stronger company/vacancy evidence. Strict filters yielding zero are normal and do not trigger demo imports.

## Google Sheets, Telegram, n8n and credentials

- Google Sheets API can be used within its free quotas without enabling billing. Create a free Google Cloud project, enable Sheets API, use service-account/ADC credentials and share a dedicated spreadsheet as documented in SETUP. Those are authentication credentials, not a paid API key. If organizational account policy prevents this, local SQLite still works. Check Google's current quota and account policies; avoid paid hosting/add-ons.
- Telegram bots and a self-hosted n8n Community Edition need no paid plans. Bot token/chat ID and the local API bearer token are still required for authentication. Never place them in committed files or chat.
- No paid AI is needed. Local relevance is advisory and never excludes lower-scoring leads or determines summer eligibility.
- Repository workflow JSON retains configurable schedules; nothing modifies deployed workflows or existing Docker containers. Import/update the intended workflow files manually after review. Automatic email sending stays disabled.

Network access is separate from cost. Grant only the needed public hosts: `query.wikidata.org`, `en.wikipedia.org`, `ar.wikipedia.org`, `www.wikidata.org`, `codeload.github.com`, `raw.githubusercontent.com`, relevant employer/feed hosts, `boards-api.greenhouse.io`, `api.lever.co`/`api.eu.lever.co` where discovered, and `overpass-api.de` for configured local inventories. No API key can fix a managed egress denial. Source-page SSRF checks require public DNS resolution on the runtime; a proxy-only DNS environment may not satisfy that check. Do not disable checks or bypass proxy restrictions to make a test pass.

References: [Overpass public API](https://wiki.openstreetmap.org/wiki/Overpass_API), [OSM attribution/license](https://www.openstreetmap.org/copyright), [MediaWiki API](https://www.mediawiki.org/wiki/API:Main_page), [Wikidata access](https://www.wikidata.org/wiki/Wikidata:Data_access), [Remote In Tech](https://github.com/remoteintech/remote-jobs), [community internship publisher](https://github.com/SimplifyJobs/Summer2027-Internships), [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html), [Lever public postings API](https://github.com/lever/postings-api), [Sheets API quotas](https://developers.google.com/workspace/sheets/api/limits).
