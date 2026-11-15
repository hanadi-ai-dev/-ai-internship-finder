# Evidence-based extraction and public LinkedIn leads (0.4)

This extends the existing free pipeline. No hosted AI, paid search key, account automation, or new service is required. Existing SQLite tables, IDs, application statuses, follow-ups, API routes and repository n8n workflows remain.

## Classification and evidence

Every newly extracted record carries `record_class` and a separate `availability`:

| record_class | Meaning |
| --- | --- |
| verified_announcement | A concrete internship/COOP/research announcement was read from a recognized employer source or an actual official-linked recruitment source. This verifies the announcement, **not** current availability or summer eligibility |
| potential_lead | Unconfirmed employer ownership, incomplete details, a detail-only card, a third-party assertion, or a public LinkedIn URL needing review |
| general_program | An evergreen career/internship program page; no specific current vacancy is established |
| closed | A past explicit closing date or a scoped statement that applications closed/position expired. It remains tracked; application status is not changed |

Availability is Unknown unless a scoped statement explicitly says applications are open, or evidence establishes closure. Opening/closing dates are only explicit, labelled ISO values or labelled HTML time datetime attributes; ambiguous dates remain blank. A past closing date or closure statement overrides an Apply link or generic “open” wording. Summer eligibility remains Unknown without the existing reviewed evidence mapping. A full-time internship or COOP is kept; a permanent engineer job mentioning previous internships, or an internship-program manager/coordinator role, is not turned into an internship.

Supported extraction includes existing JSON-LD JobPosting; article/job-card/vacancy/job-listing/data-job-id blocks; job listing table rows; and Arabic/English detail announcements. Cards and rows keep their own title, links, contacts and date evidence. A page-wide Apply button is not borrowed for unrelated cards. A detail link is recorded separately from an application method. On multi-JobPosting pages, generic page-wide email/application methods are not assigned to each job. The fetched page URL, exact source excerpt, layout and explicit dates/links are retained in extraction_evidence.

Explicit ISO dates are parsed; locale-ambiguous dates such as 03/04/2030 are not guessed. Dates in requirements are not assumed to be deadlines without a deadline label. Emails still require an explicit public mailto/structured email and contact-type evidence. No email or application URL is synthesized. A raw ATS JSON endpoint without an explicit applyUrl stays a review source, not an invented application form.

Tables/cards vary across websites; unsupported layouts and JavaScript-only pages may need an official feed/API or the existing reviewed-selector configuration. A successful fetch with no matching announcement records `no_internship_announcements` (in fetched content only); a generic Careers page records `general_program`. Neither establishes that the employer has no internships elsewhere. Generic program records remain visible in tracking/Sheets but are excluded from opportunity notifications. Closed records are excluded from new/deadline alerts. No notifications were sent during development/testing.

## Employer identity and priority

Reviewed configuration and Wikidata website claims remain distinct from independent ownership proof. A conflicting hiringOrganization URL/name on a shared ATS is rejected. A directory association or social claim cannot inherit the official trust of a known employer; external announcements need an actual official referral. Lower-trust imports cannot overwrite stronger evidence. Exact source/application aliases and structured identifiers retain existing status/follow-up and separate distinct posting years.

Local priority_score and priority_reasons favor KAUST/KACST/Wadi Jeddah, technical employers, research/universities, government, banking/finance, healthcare, startups/SMEs and broad corporations. Scores are routing/relevance estimates, not verified department facts or exclusions. Diplomatic missions are deprioritized and retained. Candidate processing and company alerts prefer higher priorities. Target/nearby cities are query/location hints unless the source provides an actual workplace location.

`nearby_locations` now supplements the existing Jeddah/Riyadh/Thuwal aliases with configurable Makkah/Mecca/مكة and Rabigh/رابغ. This does not rename those cities as Jeddah or certify commuting suitability. Existing geographic inventory boxes remain configurable.

## LinkedIn: URL-only, permitted discovery

The service **never requests LinkedIn or lnkd.in**, including through its normal fetcher, API transport or diagnostics. It never logs into LinkedIn, scrapes public Jobs HTML, runs personal accounts, bypasses robots, or treats a search result as proof of an open internship. There is no free anonymous global LinkedIn search feature claimed.

Public job/post URLs can arrive from permitted published feeds, explicit employer-page links, optional already-authorized discovery providers, or an authenticated operator import. Public company posts and recruiter post URLs remain unverified; a claim about employer/recruiter identity is not certification. The URL is retained even without a title; only an observed internship-like title creates an unverified tracking row. Search/login/profile-automation URLs are rejected. Job IDs and post activity IDs deduplicate URL variants.

LinkedIn-only records have potential_lead, Unknown eligibility/availability, no assumed application method, and an empty verified_at. Observation timestamps and provenance are retained without fabricating a successful content fetch. Candidate records have no fetched_at. Their periodic review step still performs no LinkedIn request. Exact matching public application URLs can join a name-only lead to an independently verified official record without advancing verification timestamps for LinkedIn or overwriting stronger evidence. Only actual official-source evidence can upgrade the combined record; LinkedIn itself remains unfetched.

If a permitted feed or operator import supplies an explicit external application URL, it is queued separately as an unverified destination, with no employer trust inherited from LinkedIn. The destination must be fetched/checked independently. An official page linking to LinkedIn can itself verify an announcement, but that does not verify LinkedIn content; application remains manual.

Import an ignored JSON array from a local Python checkout:

```bash
.venv/bin/internships import-leads --file data/linkedin-leads.json
```

Each object accepts `url`, optional exact observed `title`, `company_name` (unverified claim), `location_hint`, `source_url` (where it was permittedly discovered), and up to ten explicit public `application_urls`. Supply actual observed URLs; no sample vacancy URL is supplied as if real. Leave title/company blank when unknown. At most 100 objects/1 MB per CLI import. Do not commit personal collections or credentials.

Equivalent authenticated API: `POST /discovery/leads`, JSON `{"leads": [ ... ]}`. Inspect `GET /discovery/candidates`, `/opportunities` and `/discovery/status`. Imports perform no messaging, LinkedIn fetch or application submission. This route works in demo against isolated demo state too. Existing n8n HTTP nodes can call it after an authorized source produces URLs; no deployed workflow was edited.

## Additional free ATS support

Existing Greenhouse, Lever and RSS/Atom remain. SmartRecruiters public Posting API support now recognizes actual published `careers.smartrecruiters.com/<company>` / `jobs.smartrecruiters.com/<company>/...` URLs. The adapter reads the documented anonymous company postings endpoint and bounded matching internship details. It retains exact released dates, source details and explicit applyUrl; it never calls submission endpoints, guesses company slugs, or requires an API key. Public detail reads are bounded by links_per_page; listing pages by max_pages_per_query. Large boards can require adjusted budgets. Employer identity conflicts are rejected.

Reference: [SmartRecruiters Posting API](https://developers.smartrecruiters.com/docs/posting-api). Its live probe was blocked in this environment; contracts and behavior were tested with controlled responses, not claimed live job data.

## Priority-site diagnostics and observed results

Run read-only diagnostics without a tracking database write:

```bash
DEMO_MODE=false .venv/bin/internships diagnose-targets
```

Or authenticated `POST /discovery/diagnose` (demo returns disabled). Diagnostics check public DNS locally and issue bounded HEAD requests through the inherited normal HTTP route to robots.txt and the homepage. These HEADs are connectivity observations, not permission to crawl and not content/announcement verification. A DNS failure can coexist with a working proxy resolver; the crawler does not disable its private-network guard to work around that. Invalid/private destinations are refused. No networking policy, certificate verification or robots restriction is bypassed.

Failures are stored as structured code/phase/http_status/message. Distinct categories include dns_local, connection, timeout, proxy_connection/proxy_access, http_access/http_error/rate_limited, robots_disallowed/robots_http_access/robots_redirect, unsupported_content and extraction_error. Transient connection/timeouts receive up to three attempts; access denials fail without blind retries. Page failures retain company/candidate state and exponential retry scheduling. Success clears the active failure. Empty fetched content is a content outcome, not a network failure. `/discovery/status` exposes failure_counts/content_outcomes; Sheets mirrors candidate details.

Live checks on 2026-11-15:

- KAUST, KACST and Wadi Jeddah: local DNS failed; separate robots/homepage HEAD paths were denied by the managed proxy with 403. This does not prove remote DNS is broken, the domains are wrong, robots disallow crawling, or that there are no internships. Content and current vacancies could not be verified. Targets remain for later retry; no guessed replacement URLs were substituted.
- SmartRecruiters: CONNECT denied with proxy 403; no live posting was verified.
- Free public source check succeeded: Remote In Tech 876 profiles and the community internship list 1,450 rows parsed. Configured local/nearby filters produced zero matches. No live Saudi vacancy was invented or certified.
- LinkedIn: deliberately not requested. Its URLs are manual-review leads only.

See VALIDATION.md for automated checks and FREE_DISCOVERY.md for the broader no-billing strategy. See WINDOWS_UPDATE.md for an update that preserves the existing Compose project/data and targets only the assistant.
