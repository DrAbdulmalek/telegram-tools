# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-07-31

### Added
- **Unified codebase** merging three previously-separate projects:
  - `telegram-channel-copier` (v1.0.0) — fast bulk copy
  - `telegram-forwarder` (v2.1) — Download-Upload bypass
  - `telegram-pipeline` (v1.0.0) — corpus extraction + Arabic preprocessing
- **TelegramClientMixin** — shared persistent event loop, session management, entity cache
- **Adaptive RateLimiter** — exponential backoff on FloodWait, relaxation on success streaks
- **StringSession support** — export once, reuse forever (HF Secrets friendly)
- **Resume support** — copy/extract operations save progress every 10 messages
- **Album/MediaGroup awareness** — grouped media forwarded as albums
- **Unified Gradio UI** with 6 tabs: Login, Channels, Copy, Forward, Extract, Help
- **Unified CLI** (`tg-tools`) with subcommands: `login`, `copy`, `forward`, `extract`, `process`
- **Docker support** — `Dockerfile` + `docker-compose.yml` ready for HF Spaces
- **Comprehensive test suite** — 60+ unit tests covering all data structures, normalizer,
  quality filter, deduplicator, segmenter, CLI parser, and auth helpers
- **CI/CD pipeline** — ruff + flake8 linting, pytest on Python 3.10/3.11/3.12,
  bandit security scan, Docker build check
- **Bilingual README** — English (README.md) + Arabic (README.ar.md)
- **Issue templates** — bug report, feature request, security contact
- **Dependabot** — weekly pip + monthly GitHub Actions updates
- **Pre-commit hooks** — flake8, bandit, ruff, pyupgrade, trailing whitespace

### Security
- `.gitignore` excludes `*.session`, `*.session-journal`, `.env`, `copier_progress.json`
- Pre-commit `detect-private-key` hook
- Bandit security scan in CI
- No credentials hardcoded anywhere in the codebase

### Documentation
- `README.md` — English quick start, installation, architecture overview
- `README.ar.md` — Arabic equivalent
- `docs/ARCHITECTURE.md` — full design notes, data flow diagrams
- `CONTRIBUTING.md` — development setup, commit convention, testing guide
- `SECURITY.md` — security policy and vulnerability reporting
- `CHANGELOG.md` — this file

## Pre-merge History

This project consolidates:

### telegram-channel-copier (archived)
- v1.0.0 (2026-06-28) — Initial release with CLI + HF Space + Colab notebook

### telegram-forwarder (active)
- v2.1 — Album support, statistics tab, Docker
- v2.0 — Generator-based progress, SESSION_STRING, persistent event loop
- v1.0 — Initial Download-Upload implementation

### telegram-pipeline (archived)
- v1.0.0 (2026-06-28) — Extract + preprocess pipeline for Arabic NLP/OCR
