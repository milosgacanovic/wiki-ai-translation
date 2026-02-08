# Constitution — DanceResource Wiki Translation Bot

## Preamble
This constitution defines the non‑negotiable rules and operating principles for the DanceResource Wiki
Translation Bot. It is the highest‑priority project document and governs all specifications, code, and
operations. Where other documents conflict with this constitution, the constitution prevails.

## 1. Scope and Purpose
1. The system is a server‑side translation bot for https://wiki.danceresource.org.
2. It must be implemented using spec‑driven development (spec‑kit): the spec is the source of truth,
   and implementation and tests are derived from it.
3. The system must use the MediaWiki Translate extension as the canonical translation system.

## 2. Hard Constraints (MUST)
1. Do not break MediaWiki wikitext structure.
2. Use the MediaWiki API only. No direct database writes. No MediaWiki extension code.
3. Publish machine translations without requiring human review.
4. Every translated page must include a clear machine‑translation disclaimer that is visible to readers.
5. The system must work unattended and continuously, with safe retries and backoff.

## 3. Architectural Principles
1. The bot runs as a standalone service (not a MediaWiki plugin) on the same server as the wiki.
2. The design favors clarity and reliability over premature optimization.
3. The system is modular, at minimum with:
   - Scheduler/Watcher
   - MediaWiki API client
   - Translation engine abstraction + fallback
   - Glossary/Termbase + QA module
4. The bot is containerized via Docker and configured via environment variables or mounted config.

## 4. Data Model (Minimum Required)
The system must persist at least the following entities:
- pages (title, source_lang, last_source_rev)
- jobs (type, page_title, lang, status, priority, retries, error)
- segments (page_title, segment_key, source_text, checksum)
- translations (segment_key, lang, text, engine, created_at, qa_status)
- termbase (lang, term, preferred, forbidden, notes)
- style_guides (lang, rules_json)

## 5. Translation Workflow (Required)
1. Detect changed source pages via recentchanges (or webhook if available).
2. Create queued translation jobs with priority rules (critical pages first).
3. Fetch translation units via Translate extension APIs (prefer units over raw parsing).
4. Protect non‑translatable markup (templates, links, refs, categories, file names, URLs, code blocks,
   HTML tags, IDs) using placeholders.
5. Translate segments using a configurable MT engine with fallback.
6. Enforce glossary substitutions and restore placeholders.
7. Run QA gates and block publish on failure.
8. Write translated units back to the Translate system as draft/unreviewed content.
9. Persist the source revision ID to detect future edits.
10. Retry failed jobs with backoff and cap retries; then mark as errored.

## 6. Translation Rules
1. Preserve all MediaWiki structures: templates `{{}}`, links `[[ ]]`, refs `<ref>`, categories,
   file names, URLs, code blocks, HTML tags, and IDs.
2. Translate only human‑readable prose and labels.
3. Prefer consistency over fluency.
4. Enforce termbase substitutions after translation; unresolved terms create glossary tasks.

## 7. QA Gates (Block Publish on Fail)
1. Structural token counts preserved (templates/links/refs placeholders round‑trip).
2. No unclosed braces/brackets/tags introduced.
3. No segment dropped (segment count matches).
4. Glossary hard rules satisfied (forbidden terms absent; required terms present).
5. Detect untranslated segments (source equals target) and treat as failure.

## 8. Translation Engines
1. Implement an engine abstraction with fallback.
2. Choose a practical MT provider that supports 50+ languages.
3. Cache translations by checksum/hash to reduce cost.
4. Track engine used per translation.

## 9. Disclaimers (Non‑Negotiable)
1. Every translated page must include a visible machine‑translation disclaimer.
2. The disclaimer can be a banner, unit‑level injection, or other visible mechanism.
3. Disclaimers must remain even without human review.

## 10. Milestone Commitments (MVP)
1. Connect to MediaWiki API (login, tokens, read/write).
2. Detect changed source pages (revision tracking).
3. Pull translation units via Translate extension APIs.
4. MT a single language (sr) and write draft translations back as units.
5. Add per‑language disclaimers visible on translated pages.
6. Add QA gates.
7. Add second language (it), then expand via config.

## 11. Observability and Safety
1. Log all translation actions and QA results.
2. Categorize errors (API failure, markup error, glossary mismatch, etc.).
3. Maintain a clear job status lifecycle and retry strategy.
4. Rate‑limit edits to avoid overwhelming the wiki or translation APIs.

## 12. Governance
1. This constitution is the highest‑priority document for this project.
2. Any change to requirements must be made in the spec first, then implemented.
3. The system should remain open‑source friendly and easy to contribute to.

