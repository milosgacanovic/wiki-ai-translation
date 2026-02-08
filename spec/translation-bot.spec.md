# Translation Bot Spec

## Goals
- Implement the MVP milestones in `AGENTS.md`.
- Conform to `constitution.md`.

## Non-Goals
- No MediaWiki extension development.
- No direct DB writes to MediaWiki.

## Interfaces
- MediaWiki API
- Translation Engine(s)

## Engine Choice
- Primary MT: Google Cloud Translation v3

## MVP Checklist
- [ ] Login + token handling
- [ ] Recent changes polling + revision tracking
- [ ] Full-site ingestion/backfill (main namespace)
- [ ] Auto-wrap pages in `<translate>` if not yet enabled
- [ ] Ingest single title for testing
- [ ] Optional Translate mark API probe/call
- [ ] Fetch translation units via Translate API
- [ ] MT for `sr` and write draft units
- [ ] Visible machine translation disclaimer
- [ ] QA gates (markup integrity, placeholders, glossary)
- [ ] Add `it` language via config

## Acceptance Tests (high level)
- Jobs created for updated pages
- Backfill can enumerate all main namespace pages and enqueue jobs
- Single-title ingest wraps + enqueues when needed
- Segments preserved and reassembled correctly
- QA blocks broken output
- Disclaimers appear on translated pages
