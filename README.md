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
corpora from Telegram channels. Built on [Telethon](https://github.com/LonamiWebs/Telethon)
with a persistent event loop, adaptive rate limiting, and a unified Gradio UI.

> Consolidates three previously-separate projects (`telegram-channel-copier`,
> `telegram-forwarder`, `telegram-pipeline`) into a single cohesive codebase.

---

## 🚀 Features

| Tool | What it does | When to use |
|------|--------------|-------------|
| **⚡ Copy** | Fast bulk copy via direct media re-send | Public channels, posting rights |
| **🛡️ Forward** | Bypass "Restrict Saving Content" via Download-Upload | Protected channels (`noforwards`) |
| **📚 Extract** | Build NLP/OCR-ready corpus (texts + media) | Training data collection |
| **🔧 Process** | Arabic normalization, dedup, quality filter, segmentation | Post-extraction cleanup |

### Highlights

- **Single persistent asyncio loop** — Telethon-safe across all UI actions
- **Adaptive RateLimiter** — exponential backoff on FloodWait, relaxes on success streaks
- **StringSession support** — export once, reuse forever (HF Secrets friendly)
- **Resume support** — copy/extract operations save progress every 10 messages
- **Album/MediaGroup awareness** — grouped media forwarded as albums
- **Entity cache** — handles numeric channel IDs via `iter_dialogs` access_hash
- **Bilingual UI** — Arabic interface with English fallbacks
- **Docker-ready** — one `docker compose up` away from deployment

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
| `TG_SESSION` | Session string (alternative to phone login) | Optional |
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
│   │   ├── base.py           # TelegramClientMixin, shared loop, exceptions
│   │   ├── rate_limiter.py   # Adaptive RateLimiter (exp backoff)
│   │   ├── copier.py         # Fast bulk copy (direct re-send)
│   │   ├── forwarder.py      # Download-Upload bypass
│   │   ├── extractor.py      # Corpus builder
│   │   └── preprocess.py     # Arabic normalizer + quality + dedup + segmenter
│   ├── utils/
│   │   ├── auth.py           # Credentials from env or prompt
│   │   ├── media.py          # Media description helpers
│   │   └── progress.py       # ProgressManager + Stats
│   └── cli.py                # Unified `tg-tools` CLI
├── app.py                    # Gradio web UI (6 tabs)
├── tests/                    # Pytest suite (60+ tests)
├── docs/ARCHITECTURE.md
├── .github/                  # CI, dependabot, issue templates
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── requirements*.txt
```

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
