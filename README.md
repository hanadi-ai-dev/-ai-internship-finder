# AI Internship Discovery & Application Assistant

An evidence-first assistant for a Saudi AI student seeking summer, COOP, research, and technical internships in Jeddah, Riyadh, and Thuwal. Python handles public-source collection, SQLite tracking, Google Sheets export, Telegram notifications, and guarded email applications. Existing n8n Community Edition orchestrates the jobs; this project never replaces it.

**Free by default (0.3):** Wikidata, anonymous Arabic/English Wikimedia search, bounded OpenStreetMap organization inventories, public directory/community data, employer career pages, published RSS/Atom, and documented Greenhouse/Lever read APIs. No billing account, paid search key or hosted AI is required. Brave and remote AI are disabled unless explicitly opted into. Local bilingual relevance and existing tracking/Sheets/Telegram/n8n remain available.

Read the [zero-cost strategy and actual live-check results](docs/FREE_DISCOVERY.md). Live GitHub source parsing succeeded (876 company profiles and 1,450 internship rows), but strict local filters found zero matches; no local vacancies were verified. Other public endpoints were blocked by this environment's network policy. Sources never fall back to invented results.

## Quick start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# Set API_TOKEN in .env; shell commands below need the same token exported.
internships demo
pytest -q
uvicorn internship_assistant.api:app --host 127.0.0.1 --port 8018 --env-file .env --no-access-log
```

Use the Docker instructions in [SETUP.md](SETUP.md) if dotenv support is unavailable. For shell startup without dotenv, export only your chosen variables explicitly; never execute an untrusted .env file as shell code.

```mermaid
flowchart LR
  N[Existing n8n] --> A[Authenticated Python API]
  P[Search APIs and reviewed official sources] --> Q[Persistent verification queue]
  Q --> A
  A --> D[(SQLite: demo or live)]
  D --> G[Google Sheets]
  D --> T[Telegram]
  D --> R[Application draft and explicit approval]
  R --> S[Optional SMTP; disabled by default]
```

- Summer eligibility is **Confirmed / Possible / Unknown / Ineligible** and requires explicit evidence for any non-Unknown classification. COOP is never excluded by label or relevance score.
- Every monitored listing records an official source and check time. Application instructions distinguish recruitment emails, general contacts, and manual portals.
- Notifications deduplicate unchanged listings and daily runs. Deadlines and follow-ups use Saudi dates.
- Email sending is disabled in demo and disabled by default in live mode. No workflow submits web forms or automatically sends applications.
- SQLite is the source of truth. Google Sheets mirrors dedicated tabs, including discovery candidates and company outreach methods; change statuses through the API.
- Company targets stay visible without internships. Technical departments and query locations remain uncertain until evidence supports them. Email sending stays disabled.

Read [SETUP.md](SETUP.md), [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPMENT.md](DEVELOPMENT.md), and [CHANGELOG.md](CHANGELOG.md). API schemas are served at `/docs` on the running service. Do not expose the service publicly without TLS and access controls.
