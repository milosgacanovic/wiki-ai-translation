# DanceResource Wiki Translation Bot

Server-side translation bot for https://wiki.danceresource.org using MediaWiki API + Translate extension.

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

## Status
Bootstrap phase.

## Probe
Use `python -m bot.probe_mediawiki` to validate MediaWiki API credentials.
