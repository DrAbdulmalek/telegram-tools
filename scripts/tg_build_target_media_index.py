#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_build_target_media_index.py — index file_unique_id of ALL media already
present in @DrMalekDrive. Used by the forward script to skip candidates whose
exact media file was already delivered (robust dedup, immune to env rollbacks
that lose copy_state.txt — works regardless of source message ids).

Output: state/forward/target_media_ids.json  (sorted list + count)
Read-only pass, fast. Resumable via offset (state/forward/tmi_offset.txt).
"""
import os, sys, json, time, asyncio
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

BASE = '/home/z/my-project'
SEC = f'{BASE}/.secrets'
STATE_DIR = f'{BASE}/state/forward'
OUT = f'{STATE_DIR}/target_media_ids.json'
OFFSET = f'{STATE_DIR}/tmi_offset.txt'

API = json.load(open(f'{SEC}/telegram_api.json'))
SESSION = open(f'{SEC}/tg_string_session.txt').read().strip()
TARGET = 'DrMalekDrive'
SOFT = float(os.environ.get('REBUILD_BUDGET', '110'))
T0 = time.time()


def uid_of(msg):
    # Telethon 1.45 custom Photo lacks file_unique_id; numeric media id is
    # the stable per-file identifier (survives forwards, unique per upload).
    d = msg.document
    if d is not None:
        did = getattr(d, 'id', None) or getattr(d, 'file_unique_id', None)
        if did:
            return f'd{did}'
    p = msg.photo
    if p is not None:
        pid = getattr(p, 'id', None) or getattr(p, 'file_unique_id', None)
        if pid:
            return f'p{pid}'
    return None


async def amain():
    os.makedirs(STATE_DIR, exist_ok=True)
    min_id = 0
    if os.path.exists(OFFSET):
        try:
            min_id = int(open(OFFSET).read().strip() or 0)
        except Exception:
            min_id = 0
    uids = set()
    if os.path.exists(OUT):
        try:
            uids = set(json.load(open(OUT)))
        except Exception:
            uids = set()
    start_count = len(uids)

    client = TelegramClient(StringSession(SESSION), int(API['api_id']), API['api_hash'],
                            request_retries=2, retry_delay=1, connection_retries=2,
                            timeout=15)
    await client.connect()
    if not await client.is_user_authorized():
        print('SESSION_INVALID')
        sys.exit(3)
    target = await client.get_entity(TARGET)

    scanned = 0
    max_seen = min_id
    complete = False
    try:
        async for msg in client.iter_messages(target, limit=None, min_id=min_id,
                                              reverse=True):
            max_seen = msg.id
            scanned += 1
            if time.time() - T0 > SOFT - 10:
                print('BUDGET_OUT mid-scan', flush=True)
                break
            u = uid_of(msg)
            if u:
                uids.add(u)
        else:
            complete = True
    except errors.FloodWaitError as e:
        print(f'FLOOD_WAIT {e.seconds} (read)', flush=True)

    with open(OUT, 'w') as f:
        json.dump(sorted(uids), f)
    with open(OFFSET, 'w') as f:
        f.write(str(max_seen))
    print(f'INDEX_OK scanned={scanned} media_total={len(uids)} '
          f'new={len(uids) - start_count} max_id={max_seen} complete={complete}',
          flush=True)
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(amain())
