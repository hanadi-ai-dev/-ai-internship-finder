# Validation record — 2026-11-15

Validated in the development cloud instance using Python 3.12:

- Installation from requirements.lock, editable project installation: passed.
- Automated suite: **14 passed**. Source HTML, SMTP delivery, and transport failures are mocked; no real application email was sent.
- CLI demo import and Telegram preview: passed with two explicitly synthetic records.
- Running Python HTTP server: health, authenticated monitoring, listing, and daily notification preview passed.
- Docker Compose configuration validation: passed with the local example environment file.
- Docker build: passed using the managed host's trusted combined CA as a BuildKit secret, with TLS verification enabled. Initial missing trust and demo-file permissions were corrected.
- Non-root Docker HTTP smoke: health, demo import, listing, new notification preview, and non-writing Sheets preview all passed. Source configuration files were readable.
- Four workflow files: JSON parsing, inactive default, and absence of send actions checked by tests. Actual n8n import/execution remains unverified; no existing n8n container is present in this instance.

Not validated: live source availability/terms, real vacancy correctness, Google Sheets credentials/writes, Telegram delivery, AI-provider calls, SMTP delivery, and restoration in another cloud task. Live integrations require operator configuration and explicit validation. Broad autonomous public search is future scope; current discovery begins with reviewed official source targets. Seeds are not advertised internships.

Known non-failing warning: the selected Starlette release emits a deprecation warning for its httpx TestClient backend. All tests execute and pass.
