# Idea Generator (Public)

This repository contains the public-facing code for the idea-generator project:
- `poller.py` — polls Qdrant for pending tasks and dispatches workflow
- `decisions.py` — parses GO/NO-GO/CONFIRM/DISPUTE out of HITL issue comments (tested by `test_decisions.py`)
- `github_client.py` — GitHub API client for workflow and issue management
- `.github/workflows/pipeline-steps.yml` — main pipeline workflow
- `.github/workflows/poller.yml` — cron workflow that runs poller every 5 minutes
- `.github/workflows/tests.yml` — runs `test_decisions.py` on every push/PR

## Setup

1. Add secrets in repository settings:
   - `KILO_GATEWAY_URL`
   - `KILO_API_KEY`
   - `QDRANT_URL`
   - `QDRANT_API_KEY`
   - `PRIVATE_REPO_TOKEN` — PAT with `contents:read` on `idea-generator-private`
   - `SEARCH_PROVIDERS` — search provider pool for SCOUT/SIGNAL (see the private repo's README)
   - Optional GO notifications: `NTFY_TOPIC`, `NTFY_URL`, `NTFY_TOKEN`, `TELEGRAM_BOT_TOKEN`,
     `TELEGRAM_CHAT_ID`, `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_TO`
2. Run pipeline via Actions → Idea Generator Pipeline → Run workflow
