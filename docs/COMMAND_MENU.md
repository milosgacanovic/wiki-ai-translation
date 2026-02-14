# Command Menu (Operations)

This file is a command catalog for building a selectable operations menu.

## Base Paths
- Project root: `/opt/wiki-ai-translation`
- Compose file: `/opt/wiki-ai-translation/docker-compose.yml`
- Env file: `/opt/wiki-ai-translation/.env`
- Run reports: `/opt/wiki-ai-translation/docs/runs/`
- Generated one-off outputs: `/opt/wiki-ai-translation/docs/generated/`

## Execution Pattern
Use this prefix for all runtime commands:

```bash
cd /opt/wiki-ai-translation && docker compose -f /opt/wiki-ai-translation/docker-compose.yml run --rm bot <COMMAND>
```

Example:

```bash
cd /opt/wiki-ai-translation && docker compose -f /opt/wiki-ai-translation/docker-compose.yml run --rm bot wiki-translate-runner --poll-once
```

## Primary Command: `wiki-translate-runner`

### Common Actions
- `wiki-translate-runner --poll-once`
  - Delta pipeline once: detect source changes, enqueue, translate, approve, write run report.
- `wiki-translate-runner --poll-once --poll-limit 20`
  - Delta pipeline once, capped to 20 recentchanges entries for this cycle.
- `wiki-translate-runner --poll-once --dry-run`
  - Preview only: prints what would be queued, no queue/cursor/process writes.
- `wiki-translate-runner --poll-once --plan`
  - Compatibility alias for `--dry-run`.
- `wiki-translate-runner --clear-queue --poll-once`
  - Clear queued translation jobs, then run one delta cycle.
- `wiki-translate-runner --run-all`
  - Full ingest + queue processing for main namespace.
- `wiki-translate-runner --report-last`
  - Print last run summary JSON.
- `wiki-translate-runner --only-title "<TITLE>"`
  - Translate one source title to all `BOT_TARGET_LANGS`.
- `wiki-translate-runner --ingest-title "<TITLE>"`
  - Wrap/mark/enqueue one source title.
- `wiki-translate-runner --ingest-all`
  - Backfill ingest for all main namespace pages.

### Full Option Reference
- `--only-title <title>`: Process one source title only.
- `--ingest-title <title>`: Ingest one title (wrap + enqueue).
- `--ingest-all`: Ingest all main-namespace pages.
- `--ingest-limit <int>`: Limit number of pages during ingest-all.
- `--ingest-sleep-ms <int>`: Sleep between ingest writes.
- `--force-retranslate`: Enqueue translation even if source revision appears unchanged.
- `--max-keys <int>`: Translate only first N segments per page.
- `--run-all`: Ingest all, then process queue.
- `--plan`: Alias for dry-run (requires `--poll-once`).
- `--dry-run`: Preview delta queue only (requires `--poll-once`).
- `--report-last`: Print last run summary as JSON.
- `--retry-approve`: Retry approval for pages where assembled page had “no revisions”.
- `--clear-queue`: Delete queued `translate_page` jobs before running.
- `--no-cache`: Ignore translation cache; force MT requests.
- `--rebuild-only`: Use cache only, no MT calls.
- `--poll-once`: Process recentchanges one cycle.
- `--poll`: Run continuous recentchanges poll loop.
- `--poll-limit <int>`: Max recentchanges entries processed in one poll cycle.
- `--sync-reviewed-status`: Run reviewed-status metadata sync utility.

### Guardrails
- `--no-cache` cannot be combined with `--rebuild-only`.
- `--dry-run` currently works only with `--poll-once`.
- `--clear-queue` cannot be combined with `--dry-run`.

## Status/UI Commands
- `wiki-translate-status-ui`
  - Install/update `Template:Translation_status` and JS status banner.
- `wiki-translate-status-ui --template-only`
  - Update template only.
- `wiki-translate-status-ui --js-only`
  - Update JS only.
- `wiki-translate-status-migrate`
  - Migrate translated pages to template-based status.
- `wiki-translate-status-migrate --only-title "<TITLE>"`
  - Migrate one page only.
- `wiki-translate-status-migrate --langs sr,de,it`
  - Restrict to specific langs.
- `wiki-translate-status-migrate --limit 100`
  - Limit number of pages.
- `wiki-translate-status-migrate --dry-run`
  - Preview migration changes.
- `wiki-translate-status-sync-reviewed`
  - Sync reviewed pages metadata (used for reviewed→outdated accuracy).
- `wiki-translate-status-sync-reviewed --only-title "<TITLE>"`
  - Sync one title.
- `wiki-translate-status-sync-reviewed --langs sr,de`
  - Sync only specified langs.
- `wiki-translate-status-sync-reviewed --approve`
  - Approve translated page after sync.
- `wiki-translate-status-sync-reviewed --dry-run`
  - Preview only.
- `wiki-translate-ai-props-backfill`
  - Backfill `ai_translation_*` page props.
- `wiki-translate-ai-props-backfill --only-title "<TITLE>"`
  - Backfill one title.
- `wiki-translate-ai-props-backfill --langs sr,de`
  - Restrict languages.
- `wiki-translate-ai-props-backfill --limit 500`
  - Limit count.
- `wiki-translate-ai-props-backfill --no-compact-template`
  - Keep template parameters (do not compact).
- `wiki-translate-ai-props-backfill --sleep-ms 100`
  - Delay between writes.
- `wiki-translate-ai-props-backfill --dry-run`
  - Preview only.

## Cache / MT Cost Commands
- `wiki-translate-cache-backfill`
  - Populate cache from existing Translate units (no MT API calls).
- `wiki-translate-cache-backfill --langs sr,it,de,es,fr,nl`
  - Restrict target langs.
- `wiki-translate-cache-backfill --limit-pages 200`
  - Limit page count.
- `wiki-translate-cache-backfill --prefix "Conscious Dance Practices/"`
  - Restrict by title prefix.
- `wiki-translate-glossary-sync --lang sr --glossary-id dr-sr-glossary --gcs-bucket dr-wiki-ai-translation-bucket --replace`
  - Sync DB termbase to Google glossary.
- `wiki-translate-glossary-sync --lang <lang> --glossary-id <id> --gcs-uri gs://<bucket>/<path>.tsv --replace`
  - Use explicit GCS URI.

Glossary sync options:
- `--lang <code>`: Target language.
- `--glossary-id <id>`: GCP glossary id.
- `--gcs-bucket <name>`: Bucket name (if `--gcs-uri` not set).
- `--gcs-prefix <path>`: Prefix inside bucket (default `glossaries`).
- `--gcs-uri <gs://...>`: Explicit URI for glossary TSV.
- `--replace`: Delete/recreate glossary if it already exists.

## Repair / Utility Commands
- `wiki-translate-repair-displaytitles`
  - Repair translated display titles where source title leaked.
- `wiki-translate-repair-displaytitles --langs sr,de,it`
  - Restrict languages.
- `wiki-translate-repair-displaytitles --only-title "<TITLE>"`
  - Restrict one title.
- `wiki-translate-repair-displaytitles --sleep-ms 150`
  - Delay between edits.
- `wiki-translate-repair-displaytitles --dry-run`
  - Preview only.

## Sidebar Interface Command
Run as module:

```bash
cd /opt/wiki-ai-translation && docker compose -f /opt/wiki-ai-translation/docker-compose.yml run --rm bot python -m bot.update_sidebar
```

Options:
- `--lang <code>` (repeatable): update one or many languages.
- `--dry-run`: print intended content only.
- `--summary "<text>"`: custom edit summary.
- `--force`: edit even if normalized text matches.

## Probe Commands
- `python -m bot.probe_mediawiki`
  - Validate login + basic API wiring.
- `python -m bot.probe_translate_mark --title "Main_Page"`
  - Probe mark-for-translation API responses.
- `python -m bot.probe_translate_mark --title "<TITLE>" --action markfortranslation --revision <rev> --param translatetitle=yes`
  - Force action/params for mark probe.
- `python -m bot.probe_translate_run --title "<TITLE>" --lang sr --limit 3`
  - Probe short translation run.
- `python -m bot.probe_translate_page --title "<TITLE>"`
  - Probe translation-unit extraction for a title.

## Environment Override Examples
Pass temporary env per run:

```bash
cd /opt/wiki-ai-translation && docker compose -f /opt/wiki-ai-translation/docker-compose.yml run --rm \
  -e BOT_TARGET_LANGS=sr,de,es,fr,it,nl \
  bot wiki-translate-runner --poll-once
```

Useful env overrides:
- `BOT_TARGET_LANGS`: active target languages.
- `BOT_SKIP_TITLE_PREFIXES`: skip source title prefixes.
- `BOT_SKIP_TRANSLATION_SUBPAGES=1`: skip existing `/xx` translation pages during ingest.
- `BOT_TRANSLATE_MARK_ACTION`: mark action name (if custom endpoint is used).
- `BOT_TRANSLATE_MARK_PARAMS`: JSON params for mark action.
- `GCP_CREDENTIALS_PATH`: service account JSON path.
- `GCP_LOCATION`: regional location for glossary usage.
