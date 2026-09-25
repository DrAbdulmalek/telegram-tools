#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_rediscover_sources.py — READ-ONLY sweep of Translearners history to rebuild
state/forward/discovered.jsonl (nested fwd source channels) after env rollback.

- Iterates messages min_id=scan_cursor .. SCAN_TO (default 49861), parses fwd_from
  headers (PeerChannel), appends NEW channel ids to discovered.jsonl (dedup).
- NO forwarding, NO outbound writes -> cannot duplicate anything in the target.
- Checkpoint scan_state.txt every 500 msgs; 'done' marker at sweep completion.
- Env: SCAN_TO (default 49861), SCAN_BUDGET (default 110s).
"""
import os, sys, json, time, asyncio
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

BASE = '/home/z/my-project'
SEC = f'{BASE}/.secrets'
STATE = f'{BASE}/state/forward'
DISC = f'{STATE}/discovered.jsonl'
SCAN = f'{STATE}/scan_state.txt'

API = json.load(open(f'{SEC}/telegram_api.json'))
SESSION = open(f'{SEC}/tg_string_session.txt').read().strip()
TRANS = -1001135889451
TRANS_RAW = 1135889451
TARGET_RAW = 3913901632

TO = int(os.environ.get('SCAN_TO', '49861'))
BUDGET = float(os.environ.get('SCAN_BUDGET', '110'))
T0 = time.time()


def load_seen():
    seen = {}
    try:
        for line in open(DISC):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            cid = int(r.get('channel_id', 0))
            if cid and (cid not in seen or r.get('hop', 1) < seen[cid].get('hop', 1)):
                seen[cid] = r
    except FileNotFoundError:
        pass
    return seen


async def main():
    os.makedirs(STATE, exist_ok=True)
    seen = load_seen()
    n_known = len(seen)
    try:
        cur = open(SCAN).read().strip()
        start = 0 if cur == 'done' else int(cur or 0)
    except FileNotFoundError:
        start = 0
    if start >= TO or (cur == 'done' if 'cur' in dir() else False) or (isinstance(cur, str) and cur == 'done'):
        print(f'SCAN_DONE known={n_known}', flush=True)
        return
    client = TelegramClient(StringSession(SESSION), int(API['api_id']), API['api_hash'],
                            request_retries=2, retry_delay=1, connection_retries=2,
                            timeout=15, flood_sleep_threshold=0)
    await client.connect()
    if not await client.is_user_authorized():
        print('SESSION_INVALID')
        sys.exit(3)
    ent = await client.get_entity(TRANS)
    scanned = 0
    new = 0
    last = start
    completed = False
    try:
        async for msg in client.iter_messages(ent, limit=None, reverse=True,
                                              min_id=start, max_id=TO):
            scanned += 1
            last = msg.id
            fw = getattr(msg, 'fwd_from', None)
            if fw:
                fid = getattr(fw, 'from_id', None)
                if isinstance(fid, PeerChannel):
                    cid = int(fid.channel_id)
                    if cid != TRANS_RAW and cid != TARGET_RAW and cid not in seen:
                        rec = {'channel_id': cid, 'hop': 1, 'via': 'translearners',
                               'ts': int(time.time()),
                               'title': (getattr(fw, 'from_name', '') or '')}
                        seen[cid] = rec
                        with open(DISC, 'a') as f:
                            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                        new += 1
            if scanned % 500 == 0:
                with open(SCAN, 'w') as f:
                    f.write(str(last))
                print(f'SCAN last={last}/{TO} scanned={scanned} new={new}', flush=True)
            if time.time() - T0 > BUDGET:
                print('BUDGET_OUT', flush=True)
                break
        else:
            completed = True
    except errors.FloodWaitError as e:
        print(f'FLOOD_WAIT {e.seconds}', flush=True)
    finally:
        with open(SCAN, 'w') as f:
            f.write('done' if completed else str(last))
        try:
            await client.disconnect()
        except Exception:
            pass
    status = 'DONE' if completed else 'PARTIAL'
    print(f'SCAN_{status} range={start}->{last} scanned={scanned} '
          f'known={n_known}->{len(seen)} (+{new})', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
