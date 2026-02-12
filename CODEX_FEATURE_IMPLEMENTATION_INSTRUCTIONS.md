# Bot Instructions: Update `ai_translation_*` Props

## Purpose
These instructions are only for the MT bot (`wiki-ai-translation`).

The bot already:
- writes machine translations
- inserts template like `{{Translation_status|status=machine|source_rev_at_translation=...}}`
- marks outdated when source changes

Now it must ALSO update `ai_translation_*` pageprops via API.

## Do Not Change
- Keep existing template behavior in page content.
- Keep existing translation generation flow.
- Keep existing outdated decision logic.

## Optional change
- Simplify template to {{Translation_status|status=machine}} because source rev can be updated via API, but only if it's not needed for translation flow or it's too much work.


Add metadata API calls:

## API Endpoints
- Read: `action=aitranslationinfo`
- Write: `action=aitranslationstatus` (csrf + logged-in user with edit rights)

## Required Props
Write these on translated page `Title/<lang>`:
- `ai_translation_status`
- `ai_translation_source_rev`

Recommended also:
- `ai_translation_source_title`
- `ai_translation_source_lang` (`en`)
- `ai_translation_outdated_source_rev` (when outdated)

## Bot Flow Changes

### 1) Before writing translation
For target page `Title/<lang>`:
1. Read current metadata:
   - `api.php?action=aitranslationinfo&title=<Title/<lang>>&format=json`
2. Read latest source rev for English source page (existing bot logic).

### 2) If source changed and target is reviewed
If bot decides status should become outdated:
- Keep existing template update: `{{Translation_status|status=outdated}}`
- Add metadata write:
  - `status=outdated`
  - `outdated_source_rev=<latest source rev>`
  - `source_title=<source title>`
  - `source_lang=en`

### 3) After successful machine translation write
Keep existing template update/insertion.
Then call metadata write:
- `status=machine`
- `source_rev=<latest source rev used for translation>`
- `source_title=<source title>`
- `source_lang=en`

## Write API Payload
`POST /api.php`

Required params:
- `action=aitranslationstatus`
- `format=json`
- `title=<translated title>`
- `status=machine|reviewed|outdated`
- `token=<csrf token>`

Optional params:
- `source_rev=<int>`
- `outdated_source_rev=<int>`
- `source_title=<string>`
- `source_lang=en`
- `reviewed_by=<string>`
- `reviewed_at=<YYYY-MM-DD>`

## Minimal Examples

### Machine write complete
- `title=Foo/sr`
- `status=machine`
- `source_rev=19028`
- `source_title=Foo`
- `source_lang=en`

### Mark outdated
- `title=Foo/sr`
- `status=outdated`
- `outdated_source_rev=19035`
- `source_title=Foo`
- `source_lang=en`

## Error Handling
- If metadata write fails, log warning with page + language + source rev.
- Do not discard successful translation content write because metadata call failed.
- Retry metadata call once (short backoff).

## Verification
After bot run, this must return non-null values:
- `api.php?action=aitranslationinfo&title=<Title/<lang>>&format=json`

Expected at minimum:
- `status`
- `source_rev` for machine pages
- `outdated_source_rev` for outdated pages
