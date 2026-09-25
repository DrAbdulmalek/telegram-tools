# telegram-tools

أدوات Telethon (MTProto) لإدارة أرشفة قنوات تيليجرام وإعادة توجيه المحتوى خادمياً مع منع التكرار والتعافي من الانقطاعات.

Telethon (MTProto) toolset for server-side multi-source forwarding to a Telegram channel, with content-based dedup, crash-resume, and environment-rollback resilience. Battle-tested on a 9-year, 71k-message archive job.

## Scripts / السكربتات

| Script | Purpose |
|---|---|
| `scripts/tg_forward_to_channel.py` | **Main engine** — forwards messages from N sources (by username, marked id, or discovered channel id) into a target channel. Media-only or all-messages modes per source, adaptive pace (batch/sleep auto-tunes down on FloodWait), per-batch atomic `progress.json`, FloodWait persistence + inline retry, nested-source discovery from `fwd_from` headers (hop limit + title keyword filter), and **content-based media dedup** via a target-channel media-id index. |
| `scripts/tg_relogin2.py` | Phone-code re-login **with persistent device session**. Telegram binds `phone_code_hash` to the requesting session — the classic fresh-`StringSession()`-per-call bug always yields `PHONE_CODE_EXPIRED`. This script persists a `.session` file so `send` and `code` share one auth context, then exports a StringSession file. |
| `scripts/tg_build_target_media_index.py` | Indexes the **numeric media id** (`photo.id` / `document.id` — stable per uploaded file, survives forwards) of every media message already present in the target channel → `target_media_ids.json`. Read-only, resumable via offset. |
| `scripts/tg_rebuild_state.py` | Rebuilds forward-dedup state from the target channel's own history (`fwd_from` headers): translearners-origin `channel_post` ids → skip set; all other fwd'd source channels → discovery ledger. Read-only. |
| `scripts/tg_rediscover_sources.py` | Read-only sweep of a source group's history to rebuild the discovered-sources ledger after state loss. |
| `scripts/tg_relogin.py` | Legacy re-login (kept for reference — its `code` branch is a dead end; use `tg_relogin2.py`). |

## State files / ملفات الحالة (all under `state/forward/`)

| File | Role | Crash-safety |
|---|---|---|
| `progress.json` | per-source `last_id`, counters, adaptive pace, `flood_until` | atomic replace after **every batch** |
| `discovered.jsonl` | append-only nested-source ledger (id, hop, via, title) | append per discovery |
| `copy_state.txt` | source msg-ids already copied (id-level dedup) | append per batch |
| `target_media_ids.json` | file-level dedup: media ids already in target | atomic replace on exit |
| `rebuild_offset.txt` / `tmi_offset.txt` | rebuild/index scan cursors | written per scan round |

**Dedup strategy:** id-based skip (`copy_state.txt`) works while state survives; the **media-id index** (`target_media_ids.json`) is content-based and immune to state loss — after any rollback, rebuild it from the target channel itself (ground truth) in one read-only pass.

## Run pattern / نمط التشغيل (execution channels that kill background procs)

```bash
# forward rounds: each round is a fresh process; state on disk makes it resume-safe
for run in 1 2 3 4; do
  FWD_BUDGET=110 timeout -s KILL 130 python scripts/tg_forward_to_channel.py
done

# one-time: index what the target already contains (dedup ground truth)
REBUILD_BUDGET=110 timeout -s KILL 130 python scripts/tg_build_target_media_index.py
```

`FWD_BUDGET` / `REBUILD_BUDGET` = soft wall-clock budget inside a hard external `KILL` watchdog. The script saves state before exiting; just run it again to resume.

## Recovery lessons (hard-won) / دروس مستفادة

1. **`phone_code_hash` is session-bound.** Request the login code and submit it through the *same* session; otherwise Telegram returns `PHONE_CODE_EXPIRED` instantly.
2. **`StringSession(client.session)` is a string-parse ctor in Telethon 1.x**, not a copy constructor — use `StringSession.save(client.session)` to export a session string.
3. **Telethon 1.45 `Photo` objects have no `file_unique_id`** — use the numeric `photo.id` / `document.id` (stable per file, identical across forwards) as the content key.
4. **Never call `get_sender()`** in bulk sweeps (hangs on some entities); use `sender_id` / message attributes only.
5. Forwarded **user-origin** messages carry no source-chat marker in `fwd_from` (only `from_name`) — you cannot identify them in the destination history; content-key dedup is the only reliable net.
6. Keep all secrets in a git-ignored `.secrets/` dir; scripts never print tokens (SHA-256 fingerprints only).

## Security / الأمان

- All credentials (`api_id`, `api_hash`, phone, session strings, tokens) are read from `.secrets/` — **never** hardcoded, **never** printed, **never** committed (`.gitignore`).
- Run `rg "ghp_|1BQAN|AKIA|PRIVATE KEY" scripts/` before committing anything.

## Requirements

- Python 3.10+, `telethon >= 1.45`
- A Telegram API id/hash from my.telegram.org
