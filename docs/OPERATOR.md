# Operator Notes

## Configuration
- All secrets via environment variables.
- MediaWiki bot account required.
- MT provider API keys required.
- Store Google Cloud service account JSON in `.secrets/` and set `GCP_CREDENTIALS_PATH`.
- For glossaries, `GCP_LOCATION` must be a regional location (for example `us-central1`).
- `BOT_AUTO_WRAP=1` enables auto-wrapping main namespace pages in `<translate>...</translate>`.
- `BOT_TRANSLATE_MARK_ACTION` and `BOT_TRANSLATE_MARK_PARAMS` can be set to call a Translate
  extension API after wrapping if units are not detected.
  Example:
  `BOT_TRANSLATE_MARK_ACTION=markfortranslation`
  `BOT_TRANSLATE_MARK_PARAMS={"title":"{title}","translatetitle":"yes"}`
  If the API module is not available on your wiki, leave these empty and mark pages manually or
  enable the module server-side.

## Runtime
- The bot runs continuously, polling recent changes and processing jobs.
- Logs to stdout.
- Backfill via `wiki-translate-runner --ingest-all` (main namespace only).
- Full run (ingest + translate queue) via `wiki-translate-runner --run-all` (writes a report).
- Reports are written to `docs/runs/`.
- Print last run summary via `wiki-translate-runner --report-last`.
- During `--run-all`, a progress counter like `3/42 translate <title> (sr)` is printed.
- Use `python -m bot.probe_translate_mark` to log Translate API responses.
- Backfill cursor is stored in `ingest_state` for resume.
- API rate-limit backoff is automatic: 1s, 2s, 4s, 8s (max 5 attempts).

Recommended standard pipeline (most common production mode):
1. Cron calls `wiki-translate-runner --poll-once`.
2. Ingest detects changed source pages.
3. Ingest refreshes translation units (mark-for-translation API).
4. Jobs are enqueued and translated automatically.
5. Delta behavior is default: unchanged segments use cache, only changed segments go to MT.
6. Publish behavior is delta too: unchanged units are not rewritten; unit `1` may still update to refresh translation status/source revision metadata.
7. Cache has two levels: exact page-unit key and content checksum fallback (cross-page reuse).

Important:
- Do not rely on manual direct translation commands for normal operation.
- Use direct commands only for explicit force runs (for example `--no-cache` maintenance retranslate).
- For manual test sessions, you can clear queued translation jobs first:
  `wiki-translate-runner --clear-queue`
- For delta preview without mutating queue/cursor:
  `wiki-translate-runner --poll-once --dry-run`
- `--plan` is kept as a compatibility alias for `--dry-run` with `--poll-once`.

## Translation Status
The bot stores translation state using `{{Translation_status}}` in segment `1`.
In parallel, it writes `ai_translation_*` metadata using custom API endpoints:
- `action=aitranslationinfo` (read)
- `action=aitranslationstatus` (write)

Supported states:
- `machine`: bot can update when source changes.
- `reviewed`: bot skips translation content updates.
- `outdated`: bot skips translation content updates.

Segment `1` formatting invariant:
- Leading metadata directives must remain contiguous with no blank/new lines before first content.
- Target shape: `{{Translation_status...}}{{DISPLAYTITLE:...}}__NOTOC__<div ...>`

When source changes and state is `reviewed`, bot marks it `outdated` (metadata-only change).
The bot also writes `status=outdated` and `outdated_source_rev` through `aitranslationstatus`.

Install/update status UI artifacts:

```bash
wiki-translate-status-ui
```

Migrate existing translated pages to status template:

```bash
wiki-translate-status-migrate
```

Backfill AI props and compact templates to status-only:

```bash
wiki-translate-ai-props-backfill
```

Sync reviewed-page metadata (`source_rev_at_translation`) after human review edits:

```bash
wiki-translate-status-sync-reviewed
```

Approve synced pages in the same run:

```bash
wiki-translate-status-sync-reviewed --approve
```

## Skip Prefixes
Skip translation for titles starting with these prefixes:

```bash
BOT_SKIP_TITLE_PREFIXES=Conscious Dance Practices/InnerMotion/The Guidebook/
```

## Skip Translation Subpages
Skip `/sr`, `/sr-el`, etc. translation subpages:

```bash
BOT_SKIP_TRANSLATION_SUBPAGES=1
```

## Redirects
Redirect-only pages are skipped automatically.

## Termbase
Preferred translations are enforced post-MT via the `termbase` table.

```sql
INSERT INTO termbase (lang, term, preferred, forbidden, notes)
VALUES ('sr', 'kuriranih', 'odabranih', false, 'preferred adjective');
```

## Glossaries (Google Translate v3)
For stronger control (e.g., names that must never be translated), you can sync a glossary from the
termbase and have the MT engine use it.

1. Create/update a glossary from the termbase (requires a GCS bucket):

```bash
wiki-translate-glossary-sync --lang sr --glossary-id dr-sr-glossary --gcs-bucket YOUR_BUCKET --replace
```

2. Configure the bot to use the glossary:

```bash
BOT_GCP_GLOSSARIES={"sr":"dr-sr-glossary"}
```

Re-run the translation to apply glossary enforcement.

## Display Title Repair
If translated page titles were accidentally reset to source-language titles, repair them:

```bash
python -m bot.repair_display_titles --sleep-ms 200
```

Dry run:

```bash
python -m bot.repair_display_titles --dry-run
```

## Safety
- Edits are marked as bot edits; no visible disclaimer paragraph is injected into translated content.
- QA failures block publishing.
- Auto-wrap for translation uses `<translate>...</translate>` and is idempotent.

## Local Docker Notes
- Place Google credentials in `.secrets/` and they will be mounted into the container read-only.
