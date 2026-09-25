#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_copy_restricted.py — copy-mode copier for channels with "restrict saving
content" (noforwards). Server-side forward raises ChatForwardsRestrictedError,
so we download each item to a temp file and re-upload it as a NEW message.

Supports multiple restricted sources in one pass. Per-message resume state.
Usage:  FWD_BUDGET=110 python3 tg_copy_restricted.py
"""
import os, sys, json, time, asyncio, tempfile, traceback
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

BASE = '/home/z/my-project'
SECRETS = f'{BASE}/.secrets'
STATE = f'{BASE}/state/forward/copy_restricted.json'
TMPDIR = f'{BASE}/state/forward/tmp_copy'

API = json.load(open(f'{SECRETS}/telegram_api.json'))
SESSION = open(f'{SECRETS}/tg_string_session.txt').read().strip()
TARGET = 'DrMalekDrive'

# Restricted sources discovered so far: key -> (numeric_id, title)
SOURCES = [
    ('bonjourtranslation', 3490854898, 'Bonjour Translation'),
]

SOFT = float(os.environ.get('FWD_BUDGET', '110'))
T0 = time.time()


def budget_left():
    return SOFT - (time.time() - T0)


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + '.tmp'
    json.dump(st, open(tmp, 'w'))
    os.replace(tmp, STATE)


async def main():
    os.makedirs(TMPDIR, exist_ok=True)
    st = load_state()
    prog = st.setdefault('sources', {})
    totals = st.setdefault('total_copied', 0)
    client = TelegramClient(StringSession(SESSION), API['api_id'], API['api_hash'])
    async with client:
        target = await client.get_entity(TARGET)
        for key, raw_id, title in SOURCES:
            if budget_left() < 10:
                break
            s = prog.setdefault(key, {'ref': raw_id, 'title': title, 'last_id': 0,
                                      'copied': 0, 'failed': 0, 'done': False})
            if s.get('done'):
                continue
            ent = await client.get_entity(PeerChannel(int(raw_id)))
            # find max id once
            max_id = s.get('max_id', 0)
            if not max_id:
                async for m in client.iter_messages(ent, limit=1):
                    max_id = m.id
                s['max_id'] = max_id
                save_state(st)
            print(f'COPY {key} from {s["last_id"]} to {max_id}', flush=True)
            # offset_id fetches DOWNWARD (older) only. To reach messages newer
            # than last_id we must start above max_id and filter ascending ids.
            start_offset = (s['max_id'] + 1) if s.get('max_id') else 0
            msgs = []
            async for m in client.iter_messages(ent, limit=500, offset_id=start_offset):
                if m.id > s['last_id']:
                    msgs.append(m)
            msgs.reverse()  # ascending
            for m in msgs:
                if budget_left() < 8:
                    print('BUDGET_OUT', flush=True)
                    save_state(st)
                    return
                try:
                    if m.media is not None:
                        path = await client.download_media(m, file=TMPDIR + '/')
                        if path:
                            await client.send_file(target, path, caption=m.text or None)
                            try:
                                os.remove(path)
                            except OSError:
                                pass
                        else:
                            await client.send_message(target, m.text or '[media]')
                    else:
                        txt = (m.text or '').strip()
                        if txt:
                            await client.send_message(target, txt)
                    s['last_id'] = m.id
                    s['copied'] += 1
                    st['total_copied'] = st.get('total_copied', 0) + 1
                except errors.FloodWaitError as e:
                    st['flood_until'] = time.time() + e.seconds
                    save_state(st)
                    print(f'FLOOD_WAIT {e.seconds}', flush=True)
                    return
                except Exception as ex:
                    s['failed'] += 1
                    print(f'FAIL {key} id={m.id}: {type(ex).__name__} {str(ex)[:100]}', flush=True)
                    s['last_id'] = m.id  # skip poison message
                if s['copied'] % 5 == 0:
                    save_state(st)
                    print(f'PROG {key} {s["last_id"]}/{max_id} copied={s["copied"]}', flush=True)
                await asyncio.sleep(1.0)
            if s['last_id'] >= max_id:
                s['done'] = True
                print(f'DONE {key}: copied={s["copied"]} failed={s["failed"]}', flush=True)
            save_state(st)
    print(json.dumps({'total_copied': st.get('total_copied', 0),
                      'sources': {k: {'copied': v['copied'], 'failed': v['failed'],
                                      'last': v['last_id'], 'done': v['done']}
                                  for k, v in prog.items()}}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
