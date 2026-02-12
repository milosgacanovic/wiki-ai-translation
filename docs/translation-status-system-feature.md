# Translation Status, Locking, and JS Banner System

## Overview

This document defines the new Translation Status system for all machine-translated pages.

It replaces the current implementation where a visible disclaimer paragraph is inserted directly into translated page content.

The new system:

- Stores translation metadata using PageProps via a template
- Prevents bot overwriting of human-reviewed translations
- Marks reviewed translations as outdated when the source changes
- Displays translation status via a JS-injected banner
- Removes SEO boilerplate caused by visible disclaimer text


======================================================================
MANDATORY CHANGE: REMOVE EXISTING DISCLAIMER SYSTEM
======================================================================

The current implementation inserts a visible disclaimer paragraph into translated page content.

This must be fully removed.

Specifically:

- Delete all disclaimer injection logic from the bot.
- Do not insert any visible disclaimer text into translated article wikitext.
- Do not place disclaimer paragraphs inside translation segments.
- Replace the entire disclaimer mechanism with Template:Translation_status.
- All status messaging must be handled via JavaScript only.

No visible disclaimer text should exist in translated pages after migration.


======================================================================
TRANSLATION STATUS MODEL
======================================================================

Supported States:

- machine
  Machine translated. Bot may overwrite when source changes.

- reviewed
  Human reviewed. Bot must not overwrite.

- outdated
  Previously reviewed, but source has changed. Bot must not overwrite.

There is no "approved" state.


======================================================================
CRITICAL LOCK RULE
======================================================================

If dr_translation_status is:

- reviewed
- outdated

Then the bot MUST NOT modify the translated page content.

This applies to:

- Standard translation runs
- Rebuild-only mode
- Cache rebuild
- Any automated translation pass

The bot may update metadata only.


======================================================================
DATA MODEL (PAGEPROPS)
======================================================================

Each translated page (example: Title/sr) must store the following PageProps.

Required properties:

- dr_translation_status
- dr_source_rev_at_translation

Optional (recommended):

- dr_reviewed_at
- dr_reviewed_by
- dr_outdated_source_rev

These must be retrievable via:

action=query&prop=pageprops


======================================================================
TEMPLATE DESIGN
======================================================================

Template Name:

Template:Translation_status


Template Usage (Inserted at Top of Translated Pages)

Default machine translation:

{{Translation_status|status=machine}}

Human reviewed:

{{Translation_status|status=reviewed|reviewed_by=Username|reviewed_at=2026-02-11}}

Marked outdated by bot:

{{Translation_status|status=outdated}}


Template Requirements:

- Must output no visible content.
- Must set PageProps using parser functions.
- Must not inject disclaimer text.
- Must be safe to place at the top of all translated pages.


======================================================================
BOT LOGIC CHANGES
======================================================================

1. On Translation Creation

When creating or updating a translated page:

- Ensure {{Translation_status|status=machine}} exists at the top.
- Set dr_source_rev_at_translation to current source revision ID.


2. On Source Change Detection

When the system detects that the English source page has changed:

1. Fetch translation page PageProps.
2. Read dr_translation_status.

If status is machine:
- Proceed with translation.
- Update dr_source_rev_at_translation.

If status is reviewed:
- Do NOT translate.
- Change status to outdated.
- Set dr_outdated_source_rev to current source revision.

If status is outdated:
- Do NOT translate.


3. Rebuild-Only Mode

--rebuild-only must:

- Skip all pages where status is reviewed or outdated.


4. Missing Template Handling

If a translated page does not contain {{Translation_status}}:

- Treat as machine
- Insert template at top
- Continue normally


======================================================================
JS BANNER SYSTEM
======================================================================

Requirements:

- Banner must be injected via JavaScript (e.g., MediaWiki:Common.js).
- Banner must not exist in article wikitext.
- Banner must not affect SEO snippets.
- Banner must read PageProps via API.


Banner Variants:

machine:
"Machine translation. Help review this page."

reviewed:
"Human reviewed translation."

outdated:
"Translation is outdated compared to the English source. Update needed."

Each banner should include:
- Edit link to current page
- Optional link to source page


JS Logic Outline:

1. Detect if current page is a translated page (language subpage structure).
2. Query PageProps via API:
   action=query&prop=pageprops&titles=Current_Page
3. Read dr_translation_status.
4. Inject banner accordingly.

No banner content should be stored in page HTML.


======================================================================
MIGRATION PLAN
======================================================================

1. Remove disclaimer injection logic from the bot.
2. Create Template:Translation_status.
3. Run migration script:
   - Add template to all translated pages.
   - Set status=machine.
   - Set dr_source_rev_at_translation to current source revision.
4. Deploy JS banner.
5. Deploy updated runner logic.


======================================================================
ACCEPTANCE CRITERIA
======================================================================

- No disclaimer paragraph exists in any translated page.
- Every translated page contains {{Translation_status}}.
- Reviewed pages are never overwritten by the bot.
- Reviewed pages become outdated when source changes.
- Machine pages auto-update normally.
- JS banner reflects correct status.
- PageProps API returns correct values.
- Rebuild-only mode respects lock rule.


======================================================================
SECURITY AND GOVERNANCE
======================================================================

- Humans set reviewed.
- Bot sets only machine and outdated.
- Since edits require admin approval, reviewed state is effectively admin-controlled.
- Bot must never escalate status to reviewed.


======================================================================
NON-GOALS
======================================================================

- No partial segment locking.
- No automatic draft regeneration.
- No additional approval levels.
- No visible disclaimer content in articles.


======================================================================
SUMMARY
======================================================================

This feature replaces visible disclaimer injection with a metadata-driven translation status system.

It ensures:

- Clean SEO
- Overwrite protection for human-reviewed translations
- Automatic outdated detection
- JS-driven user messaging
- Structured translation governance
- Safe automation for large-scale multilingual expansion
