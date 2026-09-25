#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_send_books.py — send harvested translation resources to @DrMalekDrive as
documents with Arabic captions. Resumable: sent filenames appended to
state/forward/books_sent.txt. FloodWait-aware (persist + clean exit).
"""
import os, sys, json, time, asyncio
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

BASE = '/home/z/my-project'
SEC = f'{BASE}/.secrets'
STATE_DIR = f'{BASE}/state/forward'
SENT_LOG = f'{STATE_DIR}/books_sent.txt'
BOOKS = f'{BASE}/download/translation-books'
MANIFEST = f'{BOOKS}/manifest.json'

API = json.load(open(f'{SEC}/telegram_api.json'))
SESSION = open(f'{SEC}/tg_string_session.txt').read().strip()
TARGET = 'DrMalekDrive'
BUDGET = float(os.environ.get('SEND_BUDGET', '420'))
T0 = time.time()


def left():
    return BUDGET - (time.time() - T0)


def sent_set():
    s = set()
    try:
        with open(SENT_LOG) as f:
            s = {x.strip() for x in f if x.strip()}
    except FileNotFoundError:
        pass
    return s


def mark_sent(fname):
    with open(SENT_LOG, 'a') as f:
        f.write(fname + '\n')


def caption_for(m):
    repo = (m.get('repo') or '').split('/')[-1]
    path = (m.get('path') or m.get('file') or '').lower()
    size = m.get('size', 0) / 1e6
    if 'hanswehr' in path or 'dictionary.sql' in path:
        return ('📖 معجم هانز فير: العربي-الإنجليزي — المعجم المعياري للعربية '
                f'الحديثة ({size:.1f}MB، تنسيق قاعدة بيانات)\n'
                'المصدر: ' + repo + ' (بيانات مفتوحة)')
    if 'lisan' in path or 'lisanelarab' in path:
        return f'📚 لسان العرب لابن منظور — نسخة GoldenDict ({size:.1f}MB)\nالمصدر: ' + repo
    if 'arabicdictionary' in path:
        return (f'📚 معجم العربية الشامل — قاعدة بيانات مفتوحة ({size:.1f}MB)\n'
                'المصدر: مشروع الرام Arramooz')
    if 'engara' in path:
        return (f'📗 قاموس إنجليزي-عربي — مشروع ArabEyes ({size:.1f}MB، تنسيق SQL)\n'
                'بيانات مفتوحة المصدر')
    if 'en_ar' in path or path == 'data.db':
        return f'📗 قاموس إنجليزي-عربي — قاعدة بيانات ({size:.1f}MB)\nالمصدر: ' + repo
    if 'fa3il' in path:
        return f'📕 معجم أسماء الفاعل — العربية ({size:.1f}MB) | مشروع الرام'
    if 'jamid' in path:
        return f'📕 معجم الجامد (الأسماء الثابتة) — العربية ({size:.1f}MB) | مشروع الرام'
    if 'maf3oul' in path:
        return f'📕 معجم اسم المفعول — العربية ({size:.1f}MB) | مشروع الرام'
    if 'mansoub' in path:
        return f'📕 معجم الأعلام والمنصوبات — العربية ({size:.1f}MB) | مشروع الرام'
    return (f'📚 ملف مفيد للترجمة — {m.get("title") or repo} '
            f'({size:.1f}MB)\nالمصدر: ' + repo)


async def amain():
    manifest = json.load(open(MANIFEST))
    done = sent_set()
    client = TelegramClient(StringSession(SESSION), int(API['api_id']),
                            API['api_hash'], request_retries=2, retry_delay=1,
                            connection_retries=2, timeout=30)
    await client.connect()
    if not await client.is_user_authorized():
        print('SESSION_INVALID')
        sys.exit(3)
    target = await client.get_entity(TARGET)
    n = 0
    try:
        for m in manifest:
            if not m.get('downloaded'):
                continue
            f = os.path.join(BOOKS, m['file'])
            if m['file'] in done or not os.path.exists(f):
                continue
            if left() < 35:
                print('BUDGET_OUT', flush=True)
                break
            cap = caption_for(m)
            try:
                await client.send_file(target, f, caption=cap,
                                       force_document=True)
                mark_sent(m['file'])
                n += 1
                print(f'SENT {m["file"]} ({m["size"]/1e6:.1f}MB) left={int(left())}s',
                      flush=True)
                await asyncio.sleep(4)
            except errors.FloodWaitError as e:
                with open(f'{STATE_DIR}/books_flood_until.txt', 'w') as fh:
                    fh.write(str(time.time() + e.seconds))
                print(f'FLOOD_WAIT {e.seconds}', flush=True)
                break
    finally:
        await client.disconnect()
    print(f'SEND_DONE sent_this_round={n} total_sent={len(sent_set())}', flush=True)


if __name__ == '__main__':
    asyncio.run(amain())
