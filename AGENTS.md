# AGENTS.md — DanceResource Wiki Translation Bot

## Role
You are Codex, implementing a server-side translation bot for https://wiki.danceresource.org using spec-driven development (spec-kit). You must follow `constitution.md`.

## Hard Constraints
- Do NOT break MediaWiki wikitext structure.
- Use MediaWiki API only (no DB writes, no MediaWiki extension code).
- Use the MediaWiki Translate extension as the canonical translation system.
- Use `Template:Translation_status` + metadata for translation state (no visible disclaimer text in article content).
- Keep `ai_translation_*` props in sync via API (`aitranslationinfo`/`aitranslationstatus`) on machine/outdated transitions.
- System must work without human review.

## Tech Choices (default)
- Python 3.12
- Docker + docker-compose
- PostgreSQL (jobs, termbase, style guides, translation memory cache)
- Simple scheduler loop (poll recentchanges + job queue)

## MVP Milestones
1. Connect to MediaWiki API (login, tokens, read/write).
2. Detect changed source pages (revision tracking).
3. Pull a page’s translation units via Translate extension APIs (prefer units over raw wikitext parsing).
4. MT a single language (sr) and write draft translations back as units.
5. Add translation status metadata/template and JS banner (no disclaimer text in translated article body).
6. Add QA gates: markup integrity, placeholder restoration, glossary compliance.
7. Add second language (it), then expand via config.

## Translation Rules
- Preserve: templates `{{}}`, links `[[ ]]`, refs `<ref>`, categories, file names, URLs, code blocks, HTML tags, IDs.
- Translate only human-readable prose and labels.
- Prefer consistency over fluency.
- Enforce termbase substitutions post-translation; flag unresolved terms.
- Segment `1` metadata formatting is strict: keep leading metadata directives contiguous (no blank/new lines before first content token).

## Termbase / Style Guide
- Store per-language termbase + style guide in DB.
- Bootstrap automatically (AI-assisted research later); allow manual overrides.
- Unknown key terms create “glossary tasks” instead of guessing.

## Engines
- Choose a practical MT provider that supports 50+ languages.
- Implement provider abstraction + fallback.
- Cache translations by hash to reduce cost.
- Prefer content-hash cache reuse across pages (not only page/unit-key cache) when source text is identical.

## Data Model (minimum)
- `pages` (title, source_lang, last_source_rev)
- `jobs` (type, page_title, lang, status, priority, retries, error)
- `segments` (page_title, segment_key, source_text, checksum)
- `translations` (segment_key, lang, text, engine, created_at, qa_status)
- `termbase` (lang, term, preferred, forbidden?, notes)
- `style_guides` (lang, rules_json)

## QA Gates (block publish on fail)
- Structural token counts preserved (templates/links/refs placeholders round-trip).
- No unclosed braces/brackets/tags introduced.
- No segment dropped (source vs translated segment count matches).
- Glossary hard rules satisfied (forbidden terms absent; required terms present where applicable).

## Project Layout (expected)
- `/spec` (spec-kit specs)
- `/src` (bot code)
- `/migrations` (db schema)
- `/docker` (Dockerfile, compose)
- `/docs` (operator notes)
- `/docs/generated` (generated local artifacts/reports; gitignored)

## Output Expectations
- Produce small, runnable increments.
- Add tests for each core module.
- Prefer boring reliability over cleverness.
- If uncertain about a MediaWiki/Translate API detail, implement a probe script and log the exact responses.
- When updating interface namespace messages (e.g., `MediaWiki:Sidebar/{lang}`), use the MediaWiki API and ensure the bot has `editinterface` or equivalent rights.
- Put ad-hoc/generated scan outputs in `docs/generated/` (not in root `docs/`).
- Keep reviewed-state metadata in sync using `wiki-translate-status-sync-reviewed` so `reviewed -> outdated` transitions are accurate.

## Runtime Command Notes
- Standard delta run: `wiki-translate-runner --poll-once`
- Delta preview only (no queue/process/cursor writes): `wiki-translate-runner --poll-once --dry-run`
- Compatibility alias: `wiki-translate-runner --poll-once --plan`
- Queue maintenance: `wiki-translate-runner --clear-queue`
- `--clear-queue` must not be combined with `--dry-run`.
