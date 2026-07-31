# Architecture — telegram-tools

Multi-tool Telegram automation suite: message copying, channel
extraction, forwarding, ML training data pipeline. Built on Telethon
with a shared asyncio loop running on a non-daemon thread.

```
┌────────────────────────────────────────────────────────────────────┐
│                         UI LAYER                                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │ Streamlit app.py│  │ CLI (tg-tools)  │  │ Jupyter notebooks│  │
│  │  (47 KB)        │  │                 │  │                  │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬─────────┘  │
└───────────┼─────────────────────┼────────────────────┼────────────┘
            │                     │                    │
            ▼                     ▼                    ▼
┌────────────────────────────────────────────────────────────────────┐
│  CORE TOOLS LAYER  —  src/telegram_tools/core/                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ │
│  │  base    │ │ copier   │ │ extractor│ │ forwarder│ │preprocess│ │
│  │  mixin   │ │ v1.2:    │ │          │ │ parse_   │ │          │ │
│  │ daemon=  │ │ preview+ │ │          │ │ mode=None│ │          │ │
│  │ False    │ │ dedup    │ │          │ │ (was:html)│ │         │ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ client_manager.py  •  rate_limiter.py  •  telegram_bridge.py│ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────┬──────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  PIPELINE LAYER  —  automation/                                    │
│  • Channel discovery → entity resolution cache                     │
│  • Rate-limited fetch (FloodWait retry)                            │
│  • Media download (temp dir per message, cleanup in finally)       │
│  • Forwarding / copying / extraction                               │
└─────────────────────────────┬──────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│  ML TRAINING LAYER  —  training/                                   │
│  • Dataset assembly (messages + media + metadata)                  │
│  • Deduplication + quality filtering                               │
│  • Format conversion (JSONL for HF datasets)                       │
│  • HuggingFace Hub upload                                          │
└────────────────────────────────────────────────────────────────────┘
```

## P0/P1 fixes

1. **Non-daemon loop thread** — `_loop_thread` was `daemon=True`,
   which lets the interpreter kill the thread mid-operation (losing
   pending coroutines / unsaved downloads). Now `daemon=False` with a
   `_shutdown_event` + `atexit.register(_shutdown_shared_loop)` for
   clean teardown.
2. **Telethon ≥2.0 auth_key** — `export_session_string()` accessed
   `session.auth_key` directly, but Telethon ≥2.0 wraps it in a `Key`
   object. Fix: `if hasattr(auth_key, "key"): auth_key = auth_key.key`.
3. **`parse_mode=None`** — forwarder was hardcoding `parse_mode="html"`
   on every `send_message` / `send_file`, which corrupts plain text
   containing `<` or `>`. Now `parse_mode=None` (plain text).
