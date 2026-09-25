#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_rebuild_state.py — rebuild forward-dedup state from the TARGET channel itself.

After an env rollback lost copy_state.txt + most of discovered.jsonl, the
authoritative ground truth is @DrMalekDrive history: every forwarded message
carries fwd_from.from_id + fwd_from.channel_post (original source msg id).

Rebuilds:
  1. download/translearners-export/copy_state.txt  <- translearners-origin
     channel_post ids (dedup skip set for the media sweep)
  2. state/forward/discovered.jsonl (append)       <- all other fwd_from
     PeerChannel ids (hop=1, via='rebuild'), dedup on load in main script

Resumable: offset persisted to state/forward/rebuild_offset.txt (min_id).
Read-only on the target channel -> no forward-flood risk.
"""
import os, sys, json, time, asyncio
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

BASE = '/home/z/my-project'
SEC = f'{BASE}/.secrets'
STATE_DIR = f'{BASE}/state/forward'
DISC = f'{STATE_DIR}/discovered.jsonl'
OFFSET = f'{STATE_DIR}/rebuild_offset.txt'
COPY_STATE = f'{BASE}/download/translearners-export/copy_state.txt'

API = json.load(open(f'{SEC}/telegram_api.json'))
SESSION = open(f'{SEC}/tg_string_session.txt').read().strip()

TARGET = 'DrMalekDrive'
TARGET_RAW_ID = 3913901632
TRANS_RAW = 1135889451

SOFT = float(os.environ.get('REBUILD_BUDGET', '110'))


def budget_left():
    return SOFT - (time.time() - T0)


T0 = time.time()


async def amain():
    os.makedirs(STATE_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(COPY_STATE), exist_ok=True)
    min_id = 0
    if os.path.exists(OFFSET):
        try:
            min_id = int(open(OFFSET).read().strip() or 0)
        except Exception:
            min_id = 0

    client = TelegramClient(StringSession(SESSION), int(API['api_id']), API['api_hash'],
                            request_retries=2, retry_delay=1, connection_retries=2,
                            timeout=15)
    await client.connect()
    if not await client.is_user_authorized():
        print('SESSION_INVALID')
        sys.exit(3)
    target = await client.get_entity(TARGET)

    # load existing skip ids (avoid duplicate lines)
    have = set()
    if os.path.exists(COPY_STATE):
        try:
            with open(COPY_STATE) as f:
                have = {int(x) for x in f.read().split() if x.isdigit()}
        except Exception:
            have = set()

    # existing discovered ids
    disc_have = set()
    try:
        for line in open(DISC):
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    if r.get('channel_id'):
                        disc_have.add(int(r['channel_id']))
                except Exception:
                    pass
    except FileNotFoundError:
        pass

    new_skip = []
    new_disc = {}
    max_seen = min_id
    scanned = 0
    try:
        async for msg in client.iter_messages(target, limit=None, min_id=min_id,
                                              reverse=True):
            max_seen = msg.id
            scanned += 1
            if budget_left() < 10:
                print('BUDGET_OUT mid-scan', flush=True)
                break
            fw = getattr(msg, 'fwd_from', None)
            if not fw:
                continue
            fid = getattr(fw, 'from_id', None)
            if isinstance(fid, PeerChannel):
                cid = int(fid.channel_id)
                if cid == TRANS_RAW:
                    post = getattr(fw, 'channel_post', None)
                    if post and post not in have:
                        new_skip.append(post)
                        have.add(post)
                elif cid != TARGET_RAW_ID and cid not in disc_have and cid not in new_disc:
                    new_disc[cid] = {'channel_id': cid, 'hop': 1, 'via': 'rebuild',
                                     'ts': int(time.time()), 'title': ''}
        else:
            print('SCAN_COMPLETE', flush=True)
    except errors.FloodWaitError as e:
        print(f'FLOOD_WAIT {e.seconds} (read flood, will resume)', flush=True)

    if new_skip:
        with open(COPY_STATE, 'a') as f:
            f.write('\n'.join(str(x) for x in new_skip) + '\n')
    if new_disc:
        with open(DISC, 'a') as f:
            for cid, rec in new_disc.items():
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    with open(OFFSET, 'w') as f:
        f.write(str(max_seen))

    print(f'REBUILD_OK scanned={scanned} new_skip={len(new_skip)} '
          f'skip_total={len(have)} new_disc={len(new_disc)} '
          f'max_id={max_seen} complete={budget_left() > 10}', flush=True)
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(amain())
