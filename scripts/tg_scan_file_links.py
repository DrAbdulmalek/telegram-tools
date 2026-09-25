#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_scan_file_links.py — scan source channels' message TEXTS for links to
books / useful translation files (archives, PDFs, cloud hosts, GitHub).
Saves deduped candidates to state/forward/file_links.json.

Link classes:
  direct   : url ends with archive/book extension (.zip .rar .7z .pdf .epub ...)
  cloud    : mega.nz / drive.google.com / dropbox / mediafire / 4shared / archive.org
  github   : github.com repo|blob|raw links
Usage: SCAN_BUDGET=110 python3 tg_scan_file_links.py [source_key ...]
"""
import os, re, json, time, asyncio, sys
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

BASE = '/home/z/my-project'
SECRETS = f'{BASE}/.secrets'
OUT = f'{BASE}/state/forward/file_links.json'
SCANPOS = f'{BASE}/state/forward/scan_pos.json'

API = json.load(open(f'{SECRETS}/telegram_api.json'))
SESSION = open(f'{SECRETS}/tg_string_session.txt').read().strip()

# key -> (ref, title) — text scan only
SOURCES = [
    ('translearners', -1001135889451, 'Translearners'),
    ('nahwfortrans', 'NahwForTrans', 'نحو وصرف'),
    ('bonjourtranslation', 3490854898, 'Bonjour Translation'),
    ('translatorguide1', 'translatorguide1', 'دليل المترجم'),
    ('translationzf', 'TranslationZF', 'مصادر الترجمة ZF'),
    ('translationve', 'translationve', 'دهاليز الترجمة'),
    ('transskylanguagesolutions', 'TransSkylanguagesolutions', 'مقهى المترجم'),
    ('targma_amely', 'Targma_amely', 'ترجمة عملي'),
    ('translationpolice', 'translationpolice', 'شرطة الترجمة'),
    ('maqhaalmutarjim_group', 'maqhaalmutarjim_group', 'مقهى المترجم التفاعلي'),
    ('xesarth', 'xesarth', 'رُكن ترجمة كتب'),
    ('keymiftah_79', 'keymiftah_79', 'مفتاح ترجمات'),
    ('tarjamatbybasel', 'tarjamatbybasel', 'ترجمات باسل قطيش'),
]

EXTS = ('.zip', '.rar', '.7z', '.pdf', '.epub', '.mobi', '.djvu', '.doc',
        '.docx', '.iso', '.tar', '.gz', '.tgz', '.chm', '.djv')
CLOUD_HOSTS = ('mega.nz', 'mega.io', 'drive.google.com', 'docs.google.com',
               'dropbox.com', 'mediafire.com', '4shared.com', 'archive.org',
               'archivedetails', 'annas-archive', 'libgen', 'scribd', 'disk.yandex',
               'onedrive.live', '1drv.ms', 'cloud.mail.ru', 'terabox', 'pcloud')
GH_RE = re.compile(r'https?://(?:www\.)?github\.com/[A-Za-z0-9_.\-/]+', re.I)
URL_RE = re.compile(r'https?://[^\s<>"\')\]]+', re.I)

KEYWORDS = ['book', 'dict', 'translat', 'مصطلح', 'قاموس', 'معجم', 'كتاب', 'ترجم',
            'دورة', 'كورس', 'مصادر', 'مرجع', 'lexicon', 'glossary', 'idiom',
            'grammar', 'نحو', 'صرف', 'بلاغة', 'لغة', 'corpus']

SOFT = float(os.environ.get('SCAN_BUDGET', '110'))
T0 = time.time()


def classify(url):
    u = url.lower().split('?')[0]
    if any(h in u for h in ('t.me', 'telegram.me')):
        return None  # channel refs — handled by discovery, not downloads
    if u.endswith(EXTS):
        return 'direct'
    if any(h in u for h in CLOUD_HOSTS):
        return 'cloud'
    if 'github.com' in u:
        return 'github'
    return None


def load_json(path, default):
    try:
        return json.load(open(path))
    except Exception:
        return default


def save_json(path, obj):
    tmp = path + '.tmp'
    json.dump(obj, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, path)


async def main():
    only = set(sys.argv[1:])
    links = load_json(OUT, {})      # url -> {src, mid, cls, text, kw}
    pos = load_json(SCANPOS, {})    # key -> last scanned min-id (ascending scan)
    client = TelegramClient(StringSession(SESSION), API['api_id'], API['api_hash'])
    async with client:
        for key, ref, title in SOURCES:
            if only and key not in only:
                continue
            if time.time() - T0 > SOFT:
                print('BUDGET_OUT', flush=True)
                break
            try:
                ent = await client.get_entity(ref)
            except Exception as ex:
                print(f'RESOLVE_FAIL {key}: {type(ex).__name__}', flush=True)
                continue
            start = pos.get(key, 0)
            cnt = 0
            try:
                async for m in client.iter_messages(ent, limit=None, offset_id=start, reverse=False):
                    # descending from newest; we record newest-seen and stop at budget
                    txt = m.text or ''
                    if txt:
                        for u in URL_RE.findall(txt):
                            cls = classify(u)
                            if not cls:
                                continue
                            u = u.rstrip('.,;:')
                            if u in links:
                                continue
                            kw = any(k in txt.lower() for k in KEYWORDS)
                            links[u] = {'src': key, 'mid': m.id, 'cls': cls,
                                        'kw': kw, 'text': txt[:160]}
                            cnt += 1
                    pos[key] = m.id + 1  # next scan starts above this? no: keep min reached
                    pos[key] = min(x for x in [pos.get(key, 10**12), m.id])
                    if cnt and cnt % 25 == 0:
                        save_json(OUT, links)
                    if time.time() - T0 > SOFT:
                        print('BUDGET_OUT', flush=True)
                        break
            except errors.FloodWaitError as e:
                print(f'FLOOD_WAIT {e.seconds}', flush=True)
                save_json(OUT, links)
                save_json(SCANPOS, pos)
                return
            except Exception as ex:
                print(f'ERR {key}: {type(ex).__name__} {str(ex)[:80]}', flush=True)
            print(f'SCANNED {key} down_to_id={pos.get(key)} new_links={cnt} total={len(links)}', flush=True)
            save_json(OUT, links)
            save_json(SCANPOS, pos)
    save_json(OUT, links)
    save_json(SCANPOS, pos)
    # summary
    from collections import Counter
    c = Counter(v['cls'] for v in links.values())
    print(json.dumps({'total': len(links), 'by_class': dict(c)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
