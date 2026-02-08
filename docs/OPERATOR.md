# Operator Notes

## Configuration
- All secrets via environment variables.
- MediaWiki bot account required.
- MT provider API keys required.

## Runtime
- The bot runs continuously, polling recent changes and processing jobs.
- Logs to stdout.

## Safety
- Edits are marked as bot edits and include a machine-translation disclaimer.
- QA failures block publishing.
