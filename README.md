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

## Quickstart (local)
1. Create `.env` from `.env.example` and set MediaWiki + MT credentials.
2. `docker compose up --build`

Tip: for testing, set `BOT_TARGET_LANGS=sr` to limit translations to Serbian.

## Status
Bootstrap phase.

## Resilience
- Automatic backoff on API rate limits: 1s, 2s, 4s, 8s (max 5 attempts).

## Probe
Use `python -m bot.probe_mediawiki` to validate MediaWiki API credentials.
Use `python -m bot.probe_translate_mark --title "Main_Page"` to probe Translate mark API calls.

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

Print last run summary (JSON):

```bash
wiki-translate-runner --report-last
```

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

## Disclaimer Placement (Optional)
By default the disclaimer is inserted at the top of the translated page (first segment).
You can move it to a specific location by providing an anchor string per page + language:

```bash
BOT_DISCLAIMER_ANCHORS={"Welcome_to_the_DanceResource_Wiki":{"sr":"To learn what we stand for, read our Core Values, and explore the vision that moves us in the Manifesto."}}
```

If the anchor string is found in the translated segment, the disclaimer is inserted immediately after it.
If not found, the disclaimer falls back to the top.

Alternatively, you can place an invisible marker in the source wikitext (recommended for editors):

```bash
BOT_DISCLAIMER_MARKER=<!--BOT_DISCLAIMER-->
```

Place `<!--BOT_DISCLAIMER-->` in the source where the disclaimer should appear.

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

## License
Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0).
