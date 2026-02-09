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

## Disclaimer Placement
Optional per-page placement is supported with `BOT_DISCLAIMER_ANCHORS`:

```bash
BOT_DISCLAIMER_ANCHORS={"Welcome_to_the_DanceResource_Wiki":{"sr":"To learn what we stand for, read our Core Values, and explore the vision that moves us in the Manifesto."}}
```

If the anchor is found in any translated segment, the disclaimer is inserted after it.

You can also use an invisible marker in source wikitext (recommended for editors):

```bash
BOT_DISCLAIMER_MARKER=<!--BOT_DISCLAIMER-->
```

Place `<!--BOT_DISCLAIMER-->` where the disclaimer should appear.

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

## Safety
- Edits are marked as bot edits and include a machine-translation disclaimer.
- QA failures block publishing.
- Auto-wrap for translation uses `<translate>...</translate>` and is idempotent.

## Local Docker Notes
- Place Google credentials in `.secrets/` and they will be mounted into the container read-only.
