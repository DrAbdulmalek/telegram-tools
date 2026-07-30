# Architecture

## Overview

Telegram Tools is a unified Python toolkit for Telegram channel operations.
It combines three previously-separate utilities into one cohesive package,
sharing a single Telethon client lifecycle, a persistent asyncio loop, and
a unified Gradio web UI.

## Core Design Decisions

### 1. Single Persistent Event Loop

Telethon's `TelegramClient` binds itself to the running asyncio loop at
`connect()` time. Once bound, calling client methods from a different loop
causes silent failures or cryptic exceptions ("event loop must not change").

**Solution**: A single background thread runs one asyncio loop forever.
Every coroutine — from any tool, any UI tab, any CLI subcommand — is
scheduled onto this loop via `asyncio.run_coroutine_threadsafe()`.

```python
# src/telegram_tools/core/base.py
_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()

def _run(self, coro, timeout=120):
    future = asyncio.run_coroutine_threadsafe(coro, self._loop)
    return future.result(timeout=timeout)
```

### 2. TelegramClientMixin

All three tools (`TelegramCopier`, `TelegramForwarder`, `TelegramExtractor`)
inherit from `TelegramClientMixin`, which provides:

- Lazy client creation (`_ensure_client()`)
- Session management (file or StringSession)
- Entity resolution with `access_hash` cache
- Session string export (works for any session type)

### 3. Adaptive RateLimiter

A fixed delay is fragile: too low → Telegram bans you, too high → slow.
The `RateLimiter` class:

- Starts with the caller's `base_delay`
- Doubles on every `FloodWaitError` (capped at 60s)
- Relaxes back toward `base_delay` after 10 consecutive successes

### 4. Entity Cache (access_hash)

Telegram API requires a valid `access_hash` for every channel/chat.
You cannot construct `PeerChannel(id)` manually — it fails with
"Cannot find any entity" even when the ID is correct.

The only reliable source of `access_hash` is `iter_dialogs()`. We build
a `{id: entity}` cache lazily and index by both `-100xxx` and `xxx` forms.

### 5. Download-Upload Bypass

For channels with `noforwards=True`, the normal forward API is blocked.
The forwarder works around this by:

1. Downloading the media to a temp directory (`/tmp/telegram_tools_forwarder/`)
2. Re-uploading it as a fresh message via `send_file()`
3. Cleaning up the temp file in a `finally` block

This is slower than direct copy but is the only way to mirror protected content.

## Module Layout

```
src/telegram_tools/
├── __init__.py              # Public API exports
├── core/
│   ├── __init__.py
│   ├── base.py              # TelegramClientMixin + shared loop + exceptions
│   ├── rate_limiter.py      # Adaptive RateLimiter
│   ├── copier.py            # TelegramCopier (fast direct re-send)
│   ├── forwarder.py         # TelegramForwarder (Download-Upload)
│   ├── extractor.py         # TelegramExtractor + CorpusSaver
│   └── preprocess.py        # ArabicNormalizer + QualityFilter + Dedup + Segmenter
├── utils/
│   ├── auth.py              # Credentials from env / prompt
│   ├── media.py             # Media description helpers
│   └── progress.py          # ProgressManager + Stats
└── cli.py                   # Unified `tg-tools` CLI
```

## Data Flow

### Copy (fast)

```
Source Channel
    │ iter_messages(reverse=True)
    ▼
For each message:
    ├── send_message(file=message.media, text=message.text)
    ├── On FileReferenceError → refresh + retry
    ├── On FloodWaitError → sleep + retry
    └── Save progress every 10 messages
    ▼
Destination Channel
```

### Forward (bypass)

```
Source Channel (protected)
    │ iter_messages(reverse=True)
    ▼
For each message:
    ├── message.download_media(file=tmp_path)
    ├── client.send_file(dest, tmp_path, caption=...)
    ├── shutil.rmtree(tmp_path)
    └── Adaptive delay (RateLimiter)
    ▼
Destination Channel
```

### Extract (corpus builder)

```
Source Channel
    │ iter_messages(reverse=True)
    ▼
For each message:
    ├── Save text → texts/corpus.jsonl + texts/corpus.txt
    ├── Download media → media/{images,videos,audio,documents,other}/
    └── Record metadata
    ▼
output_dir/
  texts/corpus.txt        # plain text
  texts/corpus.jsonl      # with metadata
  media/...               # categorized
  metadata.json
  summary.txt
```

### Process (Arabic preprocessor)

```
input_dir/texts/corpus.{txt,jsonl}
    ↓
1. Deduplicator (exact + fuzzy SequenceMatcher)
2. ArabicNormalizer (tatweel, alef, taa marbuta, yaa, diacritics, noise)
3. QualityFilter (min length, Arabic ratio, repetition)
4. TextSegmenter (sentences / paragraphs)
    ↓
output_dir/
  clean_corpus.txt
  segments.jsonl
  segments.txt
  processing_stats.json
```

## Deployment Targets

| Platform | Entry point | Notes |
|----------|-------------|-------|
| **Local CLI** | `tg-tools <subcommand>` | Best for one-off operations |
| **Local Web UI** | `python app.py` | Best for interactive use |
| **Docker** | `docker compose up` | Production-ready, port 7860 |
| **HuggingFace Spaces** | Docker SDK | Use `SESSION_STRING` Secret, not phone login |

## Testing Strategy

- **Unit tests** (`tests/test_*.py`): 60+ tests covering all data structures,
  normalizer, quality filter, deduplicator, segmenter, CLI parser, auth helpers
- **Live Telegram tests**: Skipped in CI — require real credentials.
  Run manually with `TG_API_ID=... TG_API_HASH=... pytest tests/ -v`

## Security Considerations

- Session files (`.session`) and `SESSION_STRING` are NEVER committed
- `.gitignore` excludes: `*.session`, `*.session-journal`, `.env`, `copier_progress.json`
- Pre-commit hooks include `detect-private-key` and `check-added-large-files`
- Bandit security scan runs in CI on every push/PR

## Performance Notes

- **Copy** is ~10× faster than **Forward** (no download/upload)
- **Forward** caps media at 120s download + 180s upload per file
- **RateLimiter** prevents FloodWait cascades that would otherwise escalate bans
- **Entity cache** is built once per session, reused across all operations
