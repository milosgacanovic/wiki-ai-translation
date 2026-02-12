# Wiki AI Translation Bot

Open-source, server-side translation bot for MediaWiki wikis using the MediaWiki API and the Translate
extension. DanceResource uses this project in production; it is referenced here as a real-world example.

## Principles
- Spec-driven development: spec is source of truth.
- Follow `constitution.md` and `AGENTS.md`.
- Never break MediaWiki wikitext structure.

## Layout
- `spec/` specs and checklists
- `src/` bot code
- `migrations/` DB schema
- `docker/` Dockerfile and compose
- `docs/` operator notes
- `docs/generated/` local/generated scan outputs and ad-hoc reports (gitignored)

## Quickstart (local)
1. Create `.env` from `.env.example` and set MediaWiki + MT credentials.
2. `docker compose up --build`

Tip: for testing, set `BOT_TARGET_LANGS=sr` to limit translations to Serbian.

## Dev Mode (No Rebuilds)
Docker uses an editable install (`pip install -e .`) and mounts the repo into `/app`,
so code changes are picked up without rebuilding the image. Rebuild only if dependencies change.

## Status
Bootstrap phase.

## Target Languages
Planned translation languages for production:
- English
- German
- Dutch
- French
- Spanish
- Italian
- Hebrew
- Danish
- Portuguese
- Polish
- Greek
- Hungarian
- Swedish
- Finnish
- Slovak
- Croatian
- Indonesian
- Arabic
- Hindi
- Norwegian
- Czech
- Korean
- Japanese
- Georgian
- Serbian
- Romanian
- Slovenian
- Luxembourgish
- Thai
- Icelandic
- Vietnamese
- Zulu
- Chinese

Language codes (for `BOT_TARGET_LANGS`):
- English: `en`
- German: `de`
- Dutch: `nl`
- French: `fr`
- Spanish: `es`
- Italian: `it`
- Hebrew: `he`
- Danish: `da`
- Portuguese: `pt`
- Polish: `pl`
- Greek: `el`
- Hungarian: `hu`
- Swedish: `sv`
- Finnish: `fi`
- Slovak: `sk`
- Croatian: `hr`
- Indonesian: `id`
- Arabic: `ar`
- Hindi: `hi`
- Norwegian: `no`
- Czech: `cs`
- Korean: `ko`
- Japanese: `ja`
- Georgian: `ka`
- Serbian: `sr`
- Romanian: `ro`
- Slovenian: `sl`
- Luxembourgish: `lb`
- Thai: `th`
- Icelandic: `is`
- Vietnamese: `vi`
- Zulu: `zu`
- Chinese: `zh`

## Resilience
- Automatic backoff on API rate limits: 1s, 2s, 4s, 8s (max 5 attempts).

## Probe
Use `python -m bot.probe_mediawiki` to validate MediaWiki API credentials.
Use `python -m bot.probe_translate_mark --title "Main_Page"` to probe Translate mark API calls.

## Sidebar Updates (Interface Namespace)
Localized sidebar navigation can be updated via a dedicated script that edits
`MediaWiki:Sidebar/{lang}` using the MediaWiki API. The bot account must have
`editinterface` (or equivalent) rights to update the interface namespace.

Update one language:

```bash
python -m bot.update_sidebar --lang he
```

Update all configured sidebar languages:

```bash
python -m bot.update_sidebar
```

## Secrets
Store Google Cloud service account JSON at `.secrets/wiki-translate-bot.json` and set
`GCP_CREDENTIALS_PATH`.

## Runner (Test Mode)
Translate a single page (safe test mode):

```bash
wiki-translate-runner --only-title "Future_Directions_and_Vision"
```

Full run (ingest + translate queue) with a report:

```bash
wiki-translate-runner --run-all
```

Reports are written to `docs/runs/`.
Generated one-off analysis outputs should go to `docs/generated/`.

Print last run summary (JSON):

```bash
wiki-translate-runner --report-last
```

Install/update translation status template + JS banner:

```bash
wiki-translate-status-ui
```

Migrate existing translated pages to `{{Translation_status}}`:

```bash
wiki-translate-status-migrate
```

Sync reviewed-page metadata (`source_rev_at_translation`) to current source revision:

```bash
wiki-translate-status-sync-reviewed
```

With approval update:

```bash
wiki-translate-status-sync-reviewed --approve
```

## Translation Cache
The bot caches translations in Postgres (`segments` + `translations`) to avoid repeat MT costs.

Cache lookup strategy:
- L1: exact page-unit key (`page_title::segment_key`) when source checksum for that unit is unchanged.
- L2: content checksum fallback (cross-page). If unit keys changed (for example after re-marking),
  the bot reuses any existing translation with the same source checksum + target language.
- Use `--no-cache` to force MT when glossary/style changes require fresh translations.

Backfill the cache from existing Translate units (no MT calls):

```bash
wiki-translate-cache-backfill
```

Rebuild pages using cached translations only (no MT calls):

```bash
wiki-translate-runner --run-all --rebuild-only
```

Force re-translate (ignore cache):

```bash
wiki-translate-runner --run-all --no-cache
```

## Cron (Recent Changes)
Process recent changes once (for cron jobs):

```bash
wiki-translate-runner --poll-once
```

Delta dry-run preview (no queue/process/cursor changes):

```bash
wiki-translate-runner --poll-once --dry-run
```

Compatibility alias:

```bash
wiki-translate-runner --poll-once --plan
```

Clear queued translation jobs (manual maintenance):

```bash
wiki-translate-runner --clear-queue
```

Clear queue, then run one poll cycle:

```bash
wiki-translate-runner --clear-queue --poll-once
```

Default production flow (recommended):
- Use `wiki-translate-runner --poll-once` from cron every few minutes.
- The runner detects source page changes, refreshes translation units via mark-for-translation API,
  and enqueues translation jobs automatically.
- Translation then runs in delta mode by default (cache enabled): unchanged segments are reused from
  cache, changed segments are sent to MT.
- Avoid direct `translate_page` calls for normal automation; use them only for manual/forced runs.

## Ingestion
Backfill all main namespace pages (wraps with `<translate>` if needed and enqueues jobs):

```bash
wiki-translate-runner --ingest-all
```

Ingest a single title (useful for testing):

```bash
wiki-translate-runner --ingest-title "Main_Page"
```

Backfill is resumable using a stored cursor in Postgres (`ingest_state`).

## Custom Translate API Extension
Some MediaWiki installs do not expose a write API for “Mark this page for translation.” We use a
small companion extension to expose `action=markfortranslation` so the bot can keep an API-only
workflow (required by the project’s constitution).

Extension repo:
```text
https://github.com/milosgacanovic/wiki-ai-translation-extension
```

How we use it:
1. Install and enable the extension on the wiki server.
2. Ensure the bot user has `pagetranslation` and `writeapi` rights.
3. Set the env vars below so the bot can call the API.

```bash
BOT_TRANSLATE_MARK_ACTION=markfortranslation
BOT_TRANSLATE_MARK_PARAMS={"title":"{title}","translatetitle":"yes"}
```
If the API module is unavailable, leave these empty and mark pages manually or enable it server-side.

## Translation Status System
The bot uses `{{Translation_status}}` metadata in translated pages instead of inserting visible disclaimer text into article content.

Supported status values:
- `machine`: bot can update translation when source changes.
- `reviewed`: bot must not overwrite translation content.
- `outdated`: previously reviewed, source changed; bot must not overwrite translation content.

Locking rule:
- If status is `reviewed` or `outdated`, translation runs (including `--rebuild-only`) skip content updates.
- If status is `reviewed` and source revision changed, bot marks status to `outdated` (metadata-only change).

Reviewed workflow note:
- When a human marks a page as `status=reviewed`, run `wiki-translate-status-sync-reviewed` so
  `source_rev_at_translation` is aligned with the current source revision for reliable outdated detection.

The bot writes the status template into segment `1` and updates source revision metadata.

Metadata formatting rule (segment `1`):
- Keep leading metadata directives contiguous with no blank/new lines before first content token.
- Example: `{{Translation_status...}}{{DISPLAYTITLE:...}}__NOTOC__<div ...>`
- This avoids parser-inserted leading `<p><br></p>` artifacts.

## Skip Prefixes (Optional)
Skip translation for specific subtrees by title prefix:

```bash
BOT_SKIP_TITLE_PREFIXES=Conscious Dance Practices/InnerMotion/The Guidebook/
```

## Skip Translation Subpages (Optional)
Skip `/sr`, `/sr-el`, etc. translation subpages to avoid reprocessing translated pages:

```bash
BOT_SKIP_TRANSLATION_SUBPAGES=1
```

## Termbase (Per-Language)
Preferred translations are stored in Postgres (`termbase` table) and are enforced after MT.
Example:

```sql
INSERT INTO termbase (lang, term, preferred, forbidden, notes)
VALUES ('sr', 'kuriranih', 'odabranih', false, 'preferred adjective');
```

Re-run the translation after adding termbase entries to apply them.

## Glossaries (Google Translate v3)
If you need stricter control (for example, person names that must never be translated), you can
sync a Google glossary from the termbase and tell the bot to use it:

```bash
wiki-translate-glossary-sync --lang sr --glossary-id dr-sr-glossary --gcs-bucket YOUR_BUCKET --replace
```

```bash
BOT_GCP_GLOSSARIES={"sr":"dr-sr-glossary"}
```

## License
Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).
