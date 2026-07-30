# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-07-31

### Added — Bilingual Medical Pipeline
- **`pipeline/bilingual_extractor.py`** — Hybrid (English ↔ Arabic) extractor with
  three strategies (structured / sequential / contextual) and a `hybrid` default
  that applies them in confidence order per paragraph. **Zero medical
  normalization**: diacritics, ta-marbuta, alef variants, and case are preserved
  verbatim — only structural `\t` / `\n` characters inside a field are replaced
  to keep the TSV columns intact.
- **`pipeline/aligner.py`** — `BilingualAligner` alias for backward compatibility
  with early drafts that used that name.
- **`pipeline/splitter.py`** — `DatasetSplitter` with deterministic seeded
  shuffle (`seed=42` default) to break the alphabetical bias inherent to
  dictionary corpora. Outputs both strict `English\tArabic` TSV and
  HuggingFace-style JSONL (`{"translation": {"en": ..., "ar": ...}}`).
- **`pipeline/pytorch_dataset.py`** — `MedicalBilingualDataset` for `Seq2SeqTrainer`
  with NLLB-200 / mBART-50 / MarianMT. Returns `input_ids`, `attention_mask`,
  `labels` (padding masked to -100), and preserves raw text for debugging.
- **`pipeline/ocr_dataset.py`** — `MedicalOCRDataset` for Vision-Encoder-Decoder
  training (TrOCR printed/handwritten, Donut). Pairs images downloaded by
  `TelegramExtractor` with their message captions as ground-truth.
- **`pipeline/hf_uploader.py`** — One-click uploader publishing an `ml_splits/`
  directory to HuggingFace Hub as a private or public dataset repo.
- **`core/client_manager.py`** — `TelegramClientManager` singleton owning a
  persistent background asyncio loop, for safe reuse across Gradio callbacks.
- **`core/telegram_bridge.py`** — `TelegramBridge` linking Telethon message
  fetching to `BilingualExtractor` with a Batch & Preview API (returns
  `(pairs, raw_text)` so the UI can show a preview before persisting).

### Added — Automation & Training
- **`automation/headless_sync.py`** — Full CLI pipeline:
  fetch → extract → split → save TSV/JSONL → optional HF upload. Designed
  for `cron` and GitHub Actions. Reads credentials from `TG_API_ID`,
  `TG_API_HASH`, `TG_SESSION_STRING`, `HF_TOKEN` env vars.
- **`automation/test_mock_pipeline.py`** — Smoke test with synthetic medical
  messages covering all three extraction strategies. No Telegram connection
  required.
- **`training/train_translation.py`** — End-to-end training script using
  `Seq2SeqTrainer` + `MedicalBilingualDataset` + SacreBLEU metric. Supports
  NLLB / mBART / MarianMT with `--model` flag. Optional `--push-to-hub`.
- **`training/train_ocr.py`** — End-to-end OCR training with `VisionEncoderDecoderModel`
  + `MedicalOCRDataset` + CER metric. Supports TrOCR printed/handwritten.

### Added — CI/CD
- **`.github/workflows/weekly_sync.yml`** — Scheduled weekly GitHub Action
  (every Sunday 03:00 UTC) that runs the headless sync pipeline and uploads
  the result to HuggingFace Hub. Also supports `workflow_dispatch` with
  `channel` and `limit` inputs.

### Added — Tests
- **`tests/test_bilingual_pipeline.py`** — 19 tests covering all extraction
  strategies, dedup, verbatim preservation, TSV round-trip, internal
  tab/newline replacement, stats, and the full splitter lifecycle (ratios,
  shuffle determinism, TSV + JSONL output).
- **`tests/test_client_manager.py`** — 8 tests for the singleton mechanics,
  loop initialization, and `TelegramBridge.extract` shortcut.

### Added — Dependencies
- **`requirements-ml.txt`** — Optional ML dependencies (torch, transformers,
  accelerate, evaluate, sacrebleu, Pillow, huggingface_hub) split out so
  the core package stays installable without PyTorch.

### Documentation
- **`README.md`** — Added "ML Pipeline (v1.1.0)" section with architecture
  diagram, CLI quick start, and extraction-modes reference table. Updated
  features table, highlights, project structure, and environment variables.
- **`README.ar.md`** — Arabic equivalent (updated separately).

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
