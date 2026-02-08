# Operator Notes

## Configuration
- All secrets via environment variables.
- MediaWiki bot account required.
- MT provider API keys required.
- Store Google Cloud service account JSON in `.secrets/` and set `GCP_CREDENTIALS_PATH`.
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
- Use `python -m bot.probe_translate_mark` to log Translate API responses.
- Backfill cursor is stored in `ingest_state` for resume.
- API rate-limit backoff is automatic: 1s, 2s, 4s, 8s (max 5 attempts).

## Safety
- Edits are marked as bot edits and include a machine-translation disclaimer.
- QA failures block publishing.
- Auto-wrap for translation uses `<translate>...</translate>` and is idempotent.

## Local Docker Notes
- Place Google credentials in `.secrets/` and they will be mounted into the container read-only.
