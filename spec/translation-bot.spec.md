# Translation Bot Spec

## Goals
- Implement the MVP milestones in `AGENTS.md`.
- Conform to `constitution.md`.

## Non-Goals
- No MediaWiki extension development.
- No direct DB writes to MediaWiki.

## Interfaces
- MediaWiki API
- Translation Engine(s)

## MVP Checklist
- [ ] Login + token handling
- [ ] Recent changes polling + revision tracking
- [ ] Fetch translation units via Translate API
- [ ] MT for `sr` and write draft units
- [ ] Visible machine translation disclaimer
- [ ] QA gates (markup integrity, placeholders, glossary)
- [ ] Add `it` language via config

## Acceptance Tests (high level)
- Jobs created for updated pages
- Segments preserved and reassembled correctly
- QA blocks broken output
- Disclaimers appear on translated pages
