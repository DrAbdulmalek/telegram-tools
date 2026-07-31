---
title: Telegram Tools
emoji: 📨
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# 📨 Telegram Tools

[![CI](https://github.com/DrAbdulmalek/telegram-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/DrAbdulmalek/telegram-tools/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-blue)](https://huggingface.co/spaces/DrAbdulmalek/telegram-tools)

**Unified Telegram toolkit** — copy, forward, extract, and preprocess Arabic text
corpora from Telegram channels, then **align bilingual (English ↔ Arabic) medical
pairs, split them into ML-ready train/val/test sets, and publish to HuggingFace Hub**.
Built on [Telethon](https://github.com/LonamiWebs/Telethon) with a persistent event
loop, adaptive rate limiting, and a unified Gradio UI.

> ### Product role (read me first)
>
> This repo is a **training-data feeder** for
> [`omni-medical-suite`](https://github.com/DrAbdulmalek/omni-medical-suite),
> **not** a competing medical NLP product. Its scope is strictly:
>
> 1. Extract texts/media from Telegram channels.
> 2. Align bilingual (EN ↔ AR) pairs and split into train/val/test.
> 3. Publish the resulting datasets to HuggingFace Hub.
>
> The downstream consumer is Omni, which downloads the published
> datasets and runs the actual medical OCR/NLP training and inference.
> The optional `training/` scripts in this repo are **convenience
> helpers** (smoke-test a dataset, fine-tune a baseline model) — they
> are NOT the canonical training pipeline. The canonical pipeline lives
> in Omni. Do not duplicate training logic here that already exists in
> Omni; instead, prefer publishing the dataset and letting Omni train.
>
> Reference: `ECOSYSTEM_STATE.md` in `repo-sync-toolkit` for the full
> canonical relationships diagram.

> Consolidates three previously-separate projects (`telegram-channel-copier`,
> `telegram-forwarder`, `telegram-pipeline`) into a single cohesive codebase —
> **v1.1.0** adds a full bilingual pipeline (extractor + splitter + PyTorch Dataset
> + HuggingFace uploader) and optional training scripts for medical translation & OCR models.

---

## 🚀 Features

| Tool | What it does | When to use |
|------|--------------|-------------|
| **⚡ Copy** | Fast bulk copy via direct media re-send | Public channels, posting rights |
| **🛡️ Forward** | Bypass "Restrict Saving Content" via Download-Upload | Protected channels (`noforwards`) |
| **📚 Extract** | Build NLP/OCR-ready corpus (texts + media) | Training data collection |
| **🔧 Process** | Arabic normalization, dedup, quality filter, segmentation | Post-extraction cleanup |
| **📖 BilingualExtractor** *(new in v1.1)* | Hybrid (EN ↔ AR) pair extraction with zero medical normalization | Building bilingual glossaries from medical channels |
| **🔀 DatasetSplitter** *(new in v1.1)* | Train/Val/Test split with seeded shuffle to break alphabetical bias | Preparing dictionaries for ML training |
| **🔬 PyTorch Dataset** *(new in v1.1)* | `MedicalBilingualDataset` ready for `Seq2SeqTrainer` (NLLB / mBART) | Training medical translation models |
| **🖼️ OCR Dataset** *(new in v1.1)* | `MedicalOCRDataset` for TrOCR / Donut (image → text) | Training medical OCR on prescription/report images |
| **🚀 HF Uploader** *(new in v1.1)* | One-click dataset publish to HuggingFace Hub (private/public) | Sharing or backing up datasets |
| **🧪 Training helpers** *(optional, v1.1)* | `training/train_translation.py` + `training/train_ocr.py` | Convenience smoke-tests / baselines. Canonical training lives in Omni. |

### Highlights

- **Single persistent asyncio loop** — Telethon-safe across all UI actions
- **Adaptive RateLimiter** — exponential backoff on FloodWait, relaxes on success streaks
- **StringSession support** — export once, reuse forever (HF Secrets friendly)
- **Resume support** — copy/extract operations save progress every 10 messages
- **Album/MediaGroup awareness** — grouped media forwarded as albums
- **Entity cache** — handles numeric channel IDs via `iter_dialogs` access_hash
- **Bilingual UI** — Arabic interface with English fallbacks
- **Docker-ready** — one `docker compose up` away from deployment
- **Zero medical normalization** — diacritics, ta-marbuta, alef variants preserved verbatim
- **Alphabetical bias prevention** — `DatasetSplitter` shuffles with `seed=42` before splitting
- **Headless sync** — `automation/headless_sync.py` for cron jobs and GitHub Actions
- **Training scripts** — `training/train_translation.py` (NLLB/mBART) and `training/train_ocr.py` (TrOCR)

---

## 📦 Installation

### From source

```bash
git clone https://github.com/DrAbdulmalek/telegram-tools.git
cd telegram-tools
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
pip install -e .  # installs `tg-tools` CLI
```

### Docker

```bash
docker compose up -d --build
# Open http://localhost:7860
```

---

## 🔧 Quick Start

### Web UI (recommended)

```bash
python app.py
```

Open http://localhost:7860 in your browser.

### CLI

```bash
# 1. Authenticate (one-time — saves SESSION_STRING)
export TG_API_ID=12345678
export TG_API_HASH='your_api_hash'
tg-tools login --phone +963XXXXXXXXX

# 2. Copy 100 messages from a public channel
tg-tools copy --source @public_channel --dest -1001234567890 --limit 100

# 3. Forward from a protected channel (slower, bypasses restrictions)
tg-tools forward --source @protected_channel --dest -1001234567890 --delay 3

# 4. Extract a corpus for NLP/OCR
tg-tools extract --channel @my_channel --output ./corpus --limit 500

# 5. Preprocess the Arabic corpus
tg-tools process --input ./corpus --output ./processed
```

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TG_API_ID` | Telegram API ID (from my.telegram.org) | ✅ |
| `TG_API_HASH` | Telegram API Hash | ✅ |
| `TG_PHONE` | Phone number with country code | For CLI login |
| `TG_SESSION` / `TG_SESSION_STRING` | Session string (alternative to phone login) | Optional |
| `HF_TOKEN` | HuggingFace token (for `hf_uploader` and `headless_sync --upload`) | For Hub upload |
| `PORT` | Web UI port (default: 7860) | Optional |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Gradio Web UI (app.py)                  │
│  ┌──────┐ ┌─────────┐ ┌──────┐ ┌──────────┐ ┌──────────┐   │
│  │Login │ │Channels │ │ Copy │ │ Forward  │ │ Extract  │   │
│  └──────┘ └─────────┘ └──────┘ └──────────┘ └──────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │ run_coroutine_threadsafe
                          ▼
              ┌────────────────────────┐
              │  Shared asyncio loop   │  ← single background thread
              │  (one for all clients) │
              └───────────┬────────────┘
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────┐
│  Copier     │  │  Forwarder   │  │  Extractor   │
│ (direct)    │  │ (download-   │  │ (corpus      │
│             │  │  upload)     │  │  builder)    │
└──────┬──────┘  └──────┬───────┘  └──────┬───────┘
       │                │                 │
       └────────────────┼─────────────────┘
                        ▼
              ┌──────────────────┐
              │  TelegramClient  │  ← Telethon 1.36
              │  (shared mixin)  │
              └────────┬─────────┘
                       ▼
                   Telegram API
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full design notes.

---

## 📁 Project Structure

```
telegram-tools/
├── src/telegram_tools/
│   ├── core/
│   │   ├── base.py               # TelegramClientMixin, shared loop, exceptions
│   │   ├── client_manager.py     # Singleton client manager (new in v1.1)
│   │   ├── telegram_bridge.py    # Fetch → BilingualExtractor bridge (new in v1.1)
│   │   ├── rate_limiter.py       # Adaptive RateLimiter (exp backoff)
│   │   ├── copier.py             # Fast bulk copy (direct re-send)
│   │   ├── forwarder.py          # Download-Upload bypass
│   │   ├── extractor.py          # Corpus builder
│   │   └── preprocess.py         # Arabic normalizer + quality + dedup + segmenter
│   ├── pipeline/                 # Bilingual corpus pipeline (new in v1.1)
│   │   ├── bilingual_extractor.py  # Hybrid EN↔AR extractor (3 strategies)
│   │   ├── aligner.py              # Alias for BilingualExtractor
│   │   ├── splitter.py             # Train/Val/Test split with seeded shuffle
│   │   ├── pytorch_dataset.py      # MedicalBilingualDataset for Seq2Seq training
│   │   ├── ocr_dataset.py          # MedicalOCRDataset for TrOCR / Donut
│   │   └── hf_uploader.py          # One-click HuggingFace Hub publisher
│   ├── utils/
│   │   ├── auth.py               # Credentials from env or prompt
│   │   ├── media.py              # Media description helpers
│   │   └── progress.py           # ProgressManager + Stats
│   └── cli.py                    # Unified `tg-tools` CLI
├── automation/                   # Headless & cron scripts (new in v1.1)
│   ├── headless_sync.py          # Full pipeline: fetch → extract → split → upload
│   └── test_mock_pipeline.py     # Smoke test with synthetic medical messages
├── training/                     # Model training scripts (new in v1.1)
│   ├── train_translation.py      # NLLB / mBART / MarianMT (with SacreBLEU)
│   └── train_ocr.py              # TrOCR printed / handwritten (with CER)
├── app.py                        # Gradio web UI (8 tabs)
├── tests/                        # Pytest suite (90+ tests)
├── docs/ARCHITECTURE.md
├── .github/                      # CI, weekly_sync, dependabot, issue templates
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── requirements*.txt             # Core + ML + Dev splits
```

---

## 🤖 ML Pipeline (v1.1.0)

The new bilingual pipeline turns raw Telegram messages into ML-ready datasets:

```
Telegram channel
      │
      ▼  TelegramBridge.fetch_and_extract()
┌─────────────────────────┐
│  BilingualExtractor     │  hybrid mode: structured → sequential → contextual
│  (zero normalization)   │  preserves diacritics, ta-marbuta, alef variants
└────────────┬────────────┘
             │
             ▼  returns (pairs, raw_text) for Batch & Preview
┌─────────────────────────┐
│  DatasetSplitter        │  seed=42 shuffle breaks alphabetical bias
│  (train/val/test)       │  outputs strict `English\tArabic` TSV or JSONL
└────────────┬────────────┘
             │
       ┌─────┴──────┐
       ▼            ▼
┌──────────┐  ┌──────────────┐
│ PyTorch  │  │ HuggingFace  │
│ Dataset  │  │ Uploader     │
│ (NLLB)   │  │ (private/pub)│
└────┬─────┘  └──────────────┘
     ▼
 Seq2SeqTrainer  →  Medical Translation Model
```

### Quick start (CLI)

```bash
# 1. Smoke test with mock data (no Telegram connection needed)
python -m automation.test_mock_pipeline

# 2. Headless sync: fetch → extract → split → save locally
python -m automation.headless_sync \
    --channel @dr_zaky_ortho --limit 500 --mode hybrid

# 3. Full automation: ... → upload to HuggingFace Hub
python -m automation.headless_sync \
    --channel @dr_zaky_ortho --limit 1000 \
    --upload --repo-name medical-glossary-weekly --private

# 4. Train a translation model
pip install -r requirements-ml.txt
python training/train_translation.py --epochs 5

# 5. Train an OCR model on medical images
python training/train_ocr.py --model microsoft/trocr-base-handwritten
```

### Extraction modes

| Mode | Strategy | Best for |
|------|----------|----------|
| `hybrid` *(default)* | Tries structured → sequential → contextual per block | Mixed content (recommended) |
| `structured` | Same-line patterns only (`Heart - قلب`, `قلب (Heart)`) | Glossaries with explicit separators |
| `sequential` | Adjacent lines only (EN line above AR line) | Bilingual posts with paired lines |
| `contextual` | Longest Latin + Arabic run in same paragraph | Free-flowing prose with embedded terms |

---

## 🛡️ Security Notes

- **Never share** your `API_ID`, `API_HASH`, or `SESSION_STRING`
- Session files (`.session`) are excluded from Git via `.gitignore`
- Use **environment variables** or **HF Secrets** — never hardcode credentials
- The CLI's `login` command prints `SESSION_STRING` once — copy it to Secrets and clear the terminal
- After use, consider revoking the API app at my.telegram.org
- See [SECURITY.md](SECURITY.md) for the full policy

---

## ⚠️ Disclaimer

This project is for **educational purposes only**. The author is not responsible
for any misuse or violations of Telegram's Terms of Service. Always respect
content creators' rights and use the tool only on channels where you have
permission to copy/forward content.

---

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📄 License

[MIT License](LICENSE) — © 2026 Abdulmalek Husseini

---

## 📞 Links

| Platform | Link |
|----------|------|
| **GitHub** | https://github.com/DrAbdulmalek/telegram-tools |
| **HuggingFace Spaces** | https://huggingface.co/spaces/DrAbdulmalek/telegram-tools |
| **Issues** | https://github.com/DrAbdulmalek/telegram-tools/issues |
| **Discussions** | https://github.com/DrAbdulmalek/telegram-tools/discussions |
| **Author** | [@DrAbdulmalekHusseini](https://t.me/DrAbdulmalekHusseini) |
