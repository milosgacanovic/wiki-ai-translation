# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Core Principles

- **Spec-driven development**: `spec/` is the source of truth. Update specs before implementing.
- **`constitution.md`** is the highest-priority document and overrides all other docs.
- **`AGENTS.md`** defines role, hard constraints, and MVP milestones.
- Never break MediaWiki wikitext structure.
- Only use the MediaWiki API — no direct DB writes, no MediaWiki extension code.

## Commands

### Run Tests
```bash
pytest                             # all tests
pytest tests/test_placeholders.py  # single test file
pytest -k "test_name"              # single test by name
```

### Local Development
```bash
docker compose up --build          # start with rebuild
docker compose up                  # start (editable install, code changes picked up live)
```

### CLI Entry Points
```bash
wiki-translate-runner --poll-once              # delta run (standard cron mode)
wiki-translate-runner --poll-once --dry-run    # preview only, no changes
wiki-translate-runner --run-all                # ingest all + process queue
wiki-translate-runner --only-title "Page_Title"  # single page (test mode)
wiki-translate-runner --ingest-title "Page_Title"
wiki-translate-runner --ingest-all
wiki-translate-runner --clear-queue
wiki-translate-runner --report-last
wiki-translate-runner --rebuild-only           # cache-only, no MT calls
wiki-translate-runner --no-cache               # force MT, bypass cache
wiki-translate-cache-backfill
wiki-translate-glossary-sync --lang sr --glossary-id <id> --gcs-bucket <bucket> --replace
wiki-translate-status-ui
wiki-translate-status-migrate
wiki-translate-ai-props-backfill
wiki-translate-status-sync-reviewed [--approve]
python -m bot.probe_mediawiki                  # validate MediaWiki credentials
python -m bot.probe_translate_mark --title "Main_Page"
python -m bot.repair_display_titles --sleep-ms 200
python -m bot.update_sidebar [--lang he]
```

## Architecture

The bot is a standalone Python service (not a MediaWiki plugin) that:
1. Polls MediaWiki `recentchanges` to detect source page edits.
2. Marks pages for translation (via custom API extension `action=markfortranslation`).
3. Fetches translation units via MediaWiki Translate extension APIs.
4. Protects non-translatable markup using placeholders (`placeholders.py`).
5. Sends segments to Google Translate v3 (primary MT engine).
6. Enforces termbase substitutions, runs QA gates, then writes translated units back via API.
7. Manages translation status (`machine` / `reviewed` / `outdated`) via `{{Translation_status}}` template and `ai_translation_*` page props.

### Key Modules (`src/bot/`)
| File | Responsibility |
|------|----------------|
| `runner.py` | CLI entrypoint; orchestrates ingest → queue → translate pipeline |
| `translate_page.py` | Core translation logic per page/lang; placeholder round-trip, QA gates, cache |
| `ingest.py` | Wraps pages with `<translate>` tags, marks for translation, enqueues jobs |
| `scheduler.py` | Polls `recentchanges`; feeds ingest pipeline |
| `mediawiki.py` | MediaWiki API client (login, read, write, translate units) |
| `placeholders.py` | Protect/restore templates, links, refs, URLs before/after MT |
| `segmenter.py` | Parse `<!--T:n-->` unit markers from wikitext |
| `jobs.py` | PostgreSQL job queue (enqueue, dequeue, mark done/error) |
| `db.py` | DB connection + SQL helpers (segments, translations, termbase cache) |
| `config.py` | All config via env vars (see `Config` dataclass for full list) |
| `tracker.py` | Upsert `pages` table (source revision tracking) |
| `state.py` | `ingest_state` cursor (resumable ingest/poll) |
| `run_report.py` | Run lifecycle, JSON reports to `docs/runs/` |
| `engines/google_v3.py` | Google Cloud Translation v3 engine |
| `engines/base.py` | `TranslationEngine` Protocol |
| `glossary_sync.py` | Sync termbase → GCS → Google Translate glossary |
| `transliteration.py` | Serbian Cyrillic → Latin post-processing |

### Data Model (PostgreSQL)
- `pages` — source page revision tracking
- `jobs` — translation job queue (type, page_title, lang, status, priority, retries, error)
- `segments` — per-unit source text + checksum
- `translations` — cached translated segments (keyed by segment_key + lang; also by checksum for L2 cache)
- `termbase` — per-language preferred/forbidden term substitutions
- `style_guides` — per-language rules JSON
- `ingest_state` — resumable ingest/poll cursors
- `translation_runs` — run history for reports

### Cache Strategy
- **L1**: Exact `page_title::segment_key` lookup if source checksum unchanged.
- **L2**: Content-checksum fallback (cross-page reuse when unit keys changed after re-marking).
- `BOT_CACHE_STRICT_TEMPLATES`: comma-separated template names that bypass cache if they differ.
- If re-marking changes unit keys (split/merge/reorder), DB cache is bypassed for that page in that run.

### Translation Status
- `machine`: bot may update on source change.
- `reviewed`: bot must not overwrite content; only marks `outdated` if source changes.
- `outdated`: previously reviewed, source changed; content locked.
- First source translation unit holds `{{Translation_status|...}}{{DISPLAYTITLE:...}}__NOTOC__...` — no blank lines before first content token (prevents `<p><br></p>` artifacts).

### Placeholder Convention
Tokens: `__PH<n>__` (templates, refs, URLs) and `__LINK<n>__` (wikilinks). Restored after MT.

## Environment Variables

Required:
- `MW_API_URL`, `MW_USERNAME`, `MW_PASSWORD`
- `DATABASE_URL` (PostgreSQL DSN)
- `GCP_PROJECT_ID`, `GCP_CREDENTIALS_PATH` (Google SA JSON)

Key optional:
- `BOT_TARGET_LANGS` — comma-separated lang codes (default: `sr,it`)
- `BOT_SOURCE_LANG` — default `en`
- `BOT_GCP_GLOSSARIES` — JSON map `{"sr":"glossary-id"}`
- `BOT_TRANSLATE_MARK_ACTION` / `BOT_TRANSLATE_MARK_PARAMS` — custom mark-for-translation API
- `BOT_SKIP_TITLE_PREFIXES` — comma-separated title prefixes to skip
- `BOT_SKIP_TRANSLATION_SUBPAGES` — skip `/sr`, `/de`, etc. subpages (default: `1`)
- `BOT_PIVOT_REVIEWED_MAP` — JSON map for reviewed-language pivot (e.g. `{"hr":"sr"}`)
- `BOT_CACHE_STRICT_TEMPLATES` — templates that trigger cache bypass if different
- `BOT_RESOURCE_ROW_PRESERVE_FIELDS` / `BOT_RESOURCE_ROW_TRANSLATE_FIELDS`

## QA Gates (Block Publish on Failure)
1. Structural token counts preserved (placeholders round-trip).
2. No unclosed braces/brackets/tags.
3. No segments dropped (count must match).
4. Glossary hard rules satisfied.
5. No untranslated segments (source == target treated as failure).

## Ad-hoc Analysis Outputs
Generated scan outputs and one-off reports go in `docs/generated/` (gitignored). Run reports go in `docs/runs/`. Raw run logs go in `docs/runs/raw/`.
