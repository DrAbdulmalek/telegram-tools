#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_forward_to_channel.py — v2.1 (async) multi-source server-side copier to @DrMalekDrive.

Sources:
  0)  Translearners (-1001135889451): MEDIA messages only (text corpus already
      delivered, corpus_sent.txt='done'); skips IDs already copied (copy_state.txt).
  1..11) Translation channels by username: ALL messages forwarded.
  12+) Discovered channels (parsed from fwd_from headers), hop<=2, titles
       keyword-filtered for translation relevance (user request: follow nested sources).

Resilience contract:
  - progress.json saved after EVERY batch (atomic replace) -> crash/resume safe
  - copy_state.txt appended per attempted forward (skip-set for translearners)
  - FloodWaitError -> flood_until persisted + pace downgraded + clean exit
  - adaptive pace: batch/sleep persisted; sleep floor 5s after clean streaks
  - short runs (FWD_BUDGET env, default 110s) under external hard KILL watchdog
"""
import os, sys, json, time, asyncio, traceback
from telethon import TelegramClient, errors, functions
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel

BASE = '/home/z/my-project'
SECRETS = f'{BASE}/.secrets'
STATE_DIR = f'{BASE}/state/forward'
PROG = f'{STATE_DIR}/progress.json'
DISC = f'{STATE_DIR}/discovered.jsonl'
ERRS = f'{STATE_DIR}/errors.log'
COPY_STATE = f'{STATE_DIR}/copy_state.txt'
MEDIA_INDEX = f'{STATE_DIR}/target_media_ids.json'
CORPUS_FLAG = f'{BASE}/download/translearners-export/corpus_sent.txt'
TEXTS_CSV = f'{BASE}/download/translearners-export/texts.csv'

API = json.load(open(f'{SECRETS}/telegram_api.json'))
SESSION = open(f'{SECRETS}/tg_string_session.txt').read().strip()

TARGET = 'DrMalekDrive'
TARGET_RAW_ID = 3913901632
TRANS_MARKED = -1001135889451
TRANS_RAW = 1135889451

SOFT = float(os.environ.get('FWD_BUDGET', '110'))
MAX_HOP = 2

PRIMARY = [
    ('translearners', TRANS_MARKED, 'media'),
    ('nahwfortrans', 'NahwForTrans', 'all'),
    ('anggalizy1', 'Angalizy1', 'all'),
    ('bonjourtranslation', 'BonjourTranslation', 'all'),
    ('translatorguide1', 'translatorguide1', 'all'),
    ('translationzf', 'TranslationZF', 'all'),
    ('translationve', 'translationve', 'all'),
    ('pttranslators', 'pttranslators', 'all'),
    ('transskylanguagesolutions', 'TransSkylanguagesolutions', 'all'),
    ('targma_amely', 'Targma_amely', 'all'),
    ('translationpolice', 'translationpolice', 'all'),
    ('maqhaalmutarjim_group', 'maqhaalmutarjim_group', 'all'),
    # user-added 2026-09-25
    ('xesarth', 'xesarth', 'all'),
    ('keymiftah_79', 'keymiftah_79', 'all'),
    ('tarjamatbybasel', 'tarjamatbybasel', 'all'),
]
PRIMARY_USERNAMES = {u.lower() for _, u, _t in PRIMARY if u != TRANS_MARKED}

KEYWORDS = ['translat', 'ترجم', 'لغ', 'قام', 'معجم', 'مصطلح', 'نحو', 'صرف',
            'بلاغ', 'تعلم', 'تعليم', 'angla', 'english', 'francais', 'français',
            'language', 'lingu', 'diction', 'idiom', 'grammar', 'course',
            'كورس', 'دورة', 'targma']

T0 = time.time()
DISC_SEEN = {}
SKIP = set()
TARGET_MEDIA = set()  # media file-ids already present in target channel


def media_key(msg):
    """Stable per-file key: numeric media id (photo/document), prefixed."""
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


def save_media_index():
    try:
        tmp = MEDIA_INDEX + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(sorted(TARGET_MEDIA), f)
        os.replace(tmp, MEDIA_INDEX)
    except Exception:
        pass


class BudgetExit(Exception):
    pass


def budget_left():
    return SOFT - (time.time() - T0)


def load_json(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return json.loads(json.dumps(d))


def save_json(p, o):
    tmp = p + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(o, f, ensure_ascii=False)
    os.replace(tmp, p)


def log_err(m):
    try:
        with open(ERRS, 'a') as f:
            f.write(f'{time.strftime("%m-%d %H:%M:%S")} {m}\n')
    except Exception:
        pass


def load_disc():
    d = {}
    try:
        for line in open(DISC):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            cid = r.get('channel_id')
            if cid is None:
                continue
            cid = int(cid)
            if cid not in d or r.get('hop', 1) < d[cid].get('hop', 1):
                d[cid] = r
    except FileNotFoundError:
        pass
    return d


def append_disc(rec):
    try:
        with open(DISC, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass


def load_skip():
    s = set()
    try:
        for line in open(COPY_STATE):
            line = line.strip()
            if line.isdigit():
                s.add(int(line))
    except FileNotFoundError:
        pass
    return s


def append_skip(mid):
    try:
        with open(COPY_STATE, 'a') as f:
            f.write(f'{mid}\n')
    except Exception:
        pass
    SKIP.add(mid)


def relevant_title(t):
    t = (t or '').lower()
    return any(k in t for k in KEYWORDS)


async def resolve_entity(client, ref):
    if isinstance(ref, str):
        return await client.get_entity(ref)
    if ref < 0:
        return await client.get_entity(ref)
    try:
        return await client.get_entity(PeerChannel(ref))
    except Exception:
        res = await client(functions.channels.GetChannelsRequest(id=[PeerChannel(ref)]))
        for ch in res.chats:
            if getattr(ch, 'id', None) == ref and getattr(ch, 'access_hash', None) is not None:
                return ch
        raise ValueError(f'channel {ref} not resolvable')


def record_discovery(msg, via, hop):
    if hop >= MAX_HOP:
        return
    fw = getattr(msg, 'fwd_from', None)
    if not fw:
        return
    fid = getattr(fw, 'from_id', None)
    if isinstance(fid, PeerChannel):
        cid = int(fid.channel_id)
        if cid in DISC_SEEN or cid == TRANS_RAW or cid == TARGET_RAW_ID:
            return
        DISC_SEEN[cid] = {'channel_id': cid, 'hop': hop + 1, 'via': via,
                          'ts': int(time.time()), 'title': (getattr(fw, 'from_name', '') or '')}
        append_disc(DISC_SEEN[cid])


async def do_forward(client, target, ent, key, st, batch):
    """Returns count of successfully forwarded ids. Singleton failures are logged & skipped."""
    try:
        await client.forward_messages(target, batch, from_peer=ent)
        return len(batch)
    except errors.FloodWaitError:
        raise
    except Exception as e:
        if len(batch) == 1:
            log_err(f'{key} fwd fail id={batch[0].id}: {type(e).__name__}')
            st['errors'] = st.get('errors', 0) + 1
            return 0
        mid = len(batch) // 2
        a = await do_forward(client, target, ent, key, st, batch[:mid])
        b = await do_forward(client, target, ent, key, st, batch[mid:])
        return a + b


async def forward_source(client, target, ent, key, st, prog):
    mode = st.get('type', 'all')
    batch_n = int(prog.get('pace', {}).get('batch', 10))
    sleep_s = float(prog.get('pace', {}).get('sleep', 12.0))
    clean_streak = 0
    fwd = 0
    while True:
        if budget_left() < 8:
            raise BudgetExit()
        cands = []
        max_seen = st.get('last_id', 0)
        it_err = None
        try:
            async for msg in client.iter_messages(ent, limit=200, reverse=True,
                                                  min_id=st.get('last_id', 0)):
                if msg.id > max_seen:
                    max_seen = msg.id
                if msg.action is not None:
                    continue
                if mode == 'media':
                    if msg.media is None or msg.id in SKIP:
                        continue
                    mk = media_key(msg)
                    if mk is not None and mk in TARGET_MEDIA:
                        continue
                cands.append(msg)
                if len(cands) >= batch_n:
                    break
        except errors.FloodWaitError:
            raise
        except Exception as e:
            it_err = type(e).__name__
            log_err(f'{key} iter fail @last={st.get("last_id", 0)}: {e!r}'[:220])
        if cands:
            for m in cands:
                record_discovery(m, key, st.get('hop', 0))
            ok = None
            retries = 0
            while ok is None:
                try:
                    ok = await do_forward(client, target, ent, key, st, cands)
                except errors.FloodWaitError as e:
                    if e.seconds <= min(90, budget_left() - 15) and retries < 2:
                        print(f'FLOOD_INLINE {e.seconds}s', flush=True)
                        await asyncio.sleep(e.seconds + 1)
                        retries += 1
                    else:
                        raise
            fwd += ok
            prog['total_forwarded'] = prog.get('total_forwarded', 0) + ok
            st['forwarded'] = st.get('forwarded', 0) + ok
            st['last_id'] = max_seen
            st['status'] = 'active'
            if mode == 'media':
                for m in cands:
                    append_skip(m.id)
                    mk = media_key(m)
                    if mk is not None:
                        TARGET_MEDIA.add(mk)
            if ok == len(cands):
                clean_streak += 1
                if clean_streak >= 3 and sleep_s > 5.0:
                    sleep_s = max(5.0, sleep_s - 1.0)
                    clean_streak = 0
                    prog['pace'] = {'batch': batch_n, 'sleep': sleep_s}
            save_json(PROG, prog)
            print(f'PROG {key} last={st["last_id"]}/{st.get("max_id","?")} run_fwd={fwd}', flush=True)
            await asyncio.sleep(sleep_s)
        elif it_err is not None:
            st['status'] = 'active'
            save_json(PROG, prog)
            return fwd
        elif max_seen > st.get('last_id', 0):
            st['last_id'] = max_seen
            save_json(PROG, prog)
            await asyncio.sleep(0.2)
        else:
            st['status'] = 'done'
            save_json(PROG, prog)
            print(f'SRC_DONE {key} forwarded={st.get("forwarded", 0)}', flush=True)
            return fwd


def report(prog, run_fwd):
    prim = {}
    for k, _r, _t in PRIMARY:
        v = prog['sources'].get(k, {})
        prim[k] = {'s': v.get('status'), 'fwd': v.get('forwarded', 0),
                   'last': v.get('last_id', 0), 'max': v.get('max_id'),
                   'err': v.get('errors', 0)}
    disc = {}
    for k, v in prog['sources'].items():
        if k.startswith('disc:'):
            disc[v['status']] = disc.get(v['status'], 0) + 1
    rem = int(prog.get('flood_until', 0) - time.time())
    return {'run_fwd': run_fwd, 'total_fwd': prog.get('total_forwarded', 0),
            'pace': prog.get('pace'), 'flood_remain_s': max(rem, 0),
            'skip_len': len(SKIP), 'discovered_seen': len(DISC_SEEN),
            'disc_statuses': disc, 'primary': prim}


async def amain():
    global DISC_SEEN, SKIP
    os.makedirs(STATE_DIR, exist_ok=True)
    prog = load_json(PROG, {'sources': {}, 'flood_until': 0, 'total_forwarded': 0,
                            'pace': {'batch': 10, 'sleep': 12.0}})
    DISC_SEEN = load_disc()
    SKIP = load_skip()
    try:
        TARGET_MEDIA.update(json.load(open(MEDIA_INDEX)))
    except Exception:
        pass
    print(f'STATE loaded: skip={len(SKIP)} target_media={len(TARGET_MEDIA)}', flush=True)
    changed = False
    for key, ref, typ in PRIMARY:
        if key not in prog['sources']:
            prog['sources'][key] = {'ref': ref, 'type': typ, 'hop': 0, 'status': 'pending',
                                    'last_id': 0, 'forwarded': 0, 'errors': 0,
                                    'title': 'Translearners' if key == 'translearners' else ''}
            changed = True
    for cid, rec in DISC_SEEN.items():
        key = f'disc:{cid}'
        if key not in prog['sources'] and cid != TRANS_RAW and cid != TARGET_RAW_ID:
            prog['sources'][key] = {'ref': int(cid), 'type': 'all',
                                    'hop': min(rec.get('hop', 1), MAX_HOP), 'status': 'pending',
                                    'last_id': 0, 'forwarded': 0, 'errors': 0,
                                    'title': rec.get('title', ''), 'via': rec.get('via')}
            changed = True
    if changed:
        save_json(PROG, prog)

    client = TelegramClient(StringSession(SESSION), int(API['api_id']), API['api_hash'],
                            request_retries=2, retry_delay=1, connection_retries=2,
                            timeout=15, flood_sleep_threshold=0)
    try:
        await client.connect()
    except Exception as e:
        print('CONNECT_FAIL', repr(e))
        sys.exit(3)
    if not await client.is_user_authorized():
        print('SESSION_INVALID')
        sys.exit(3)
    print(f'AUTH_OK t0_left={int(budget_left())}', flush=True)
    try:
        target = await client.get_entity(TARGET)
    except Exception as e:
        print('TARGET_RESOLVE_FAIL', repr(e))
        sys.exit(4)

    # one-time safety: texts.csv (skip if corpus flag says done)
    if not prog.get('texts_csv_sent', False) and not \
            (os.path.exists(CORPUS_FLAG) and open(CORPUS_FLAG).read().strip() == 'done') \
            and os.path.exists(TEXTS_CSV) and budget_left() > 40:
        try:
            await client.send_file(target, TEXTS_CSV, force_document=True,
                                   caption='📚 نصوص رسائل مجموعة Translearners الكاملة (2017–2026)')
            prog['texts_csv_sent'] = True
            save_json(PROG, prog)
            print('TEXTS_CSV_SENT', flush=True)
        except errors.FloodWaitError as e:
            prog['flood_until'] = time.time() + e.seconds
            save_json(PROG, prog)
        except Exception as e:
            log_err(f'texts.csv: {e!r}'[:200])

    order = [k for k, _r, _t in PRIMARY] + \
            sorted([f'disc:{c}' for c in DISC_SEEN if f'disc:{c}' in prog['sources']],
                   key=lambda k: (prog['sources'][k].get('hop', 1), k))
    run_fwd = 0
    try:
        for key in order:
            if budget_left() < 10:
                print('BUDGET_OUT', flush=True)
                break
            st = prog['sources'][key]
            if st['status'] in ('done', 'unresolved', 'filtered', 'dup_primary', 'restricted'):
                continue
            rem = prog.get('flood_until', 0) - time.time()
            if rem > 0:
                if rem > budget_left() - 8:
                    print(f'FLOOD_LATER {int(rem)}s', flush=True)
                    break
                print(f'FLOOD_SLEEP {int(rem)}s', flush=True)
                time.sleep(rem)
            try:
                ent = await resolve_entity(client, st['ref'])
            except (ValueError, errors.ChannelPrivateError) as e:
                st['status'] = 'unresolved'
                st['err'] = repr(e)[:150]
                save_json(PROG, prog)
                print(f'UNRESOLVED {key}', flush=True)
                continue
            except errors.FloodWaitError as e:
                prog['flood_until'] = time.time() + e.seconds
                save_json(PROG, prog)
                print(f'FLOOD_WAIT {e.seconds}', flush=True)
                break
            except Exception as e:
                log_err(f'{key} resolve fail: {e!r}'[:200])
                continue
            uname = (getattr(ent, 'username', '') or '').lower()
            if st.get('hop', 0) > 0 and (uname in PRIMARY_USERNAMES or
                                         getattr(ent, 'id', 0) == TRANS_RAW or
                                         getattr(ent, 'id', 0) == TARGET_RAW_ID):
                st['status'] = 'dup_primary'
                save_json(PROG, prog)
                continue
            st['title'] = getattr(ent, 'title', '') or st.get('title', '')
            if st.get('hop', 0) > 0 and not relevant_title(st['title']):
                st['status'] = 'filtered'
                save_json(PROG, prog)
                print(f'FILTERED {key} {st["title"][:60]!r}', flush=True)
                continue
            if not st.get('max_id'):
                try:
                    async for m in client.iter_messages(ent, limit=1):
                        st['max_id'] = m.id
                except Exception:
                    pass
                save_json(PROG, prog)
            try:
                run_fwd += await forward_source(client, target, ent, key, st, prog)
            except errors.FloodWaitError as e:
                prog['flood_until'] = time.time() + e.seconds
                p = prog.get('pace', {'batch': 10, 'sleep': 12.0})
                prog['pace'] = {'batch': max(5, int(p['batch']) // 2),
                                'sleep': min(90.0, float(p['sleep']) * 2)}
                save_json(PROG, prog)
                print(f'FLOOD_WAIT {e.seconds}', flush=True)
                break
            except BudgetExit:
                break
            except errors.ChatWriteForbiddenError as e:
                print('TARGET_WRITE_FORBIDDEN', repr(e))
                sys.exit(4)
            except Exception as e:
                log_err(f'{key} fatal: {e!r}\n{traceback.format_exc()[-500:]}')
                st['errors'] = st.get('errors', 0) + 1
                save_json(PROG, prog)
            if st.get('type') == 'media' and st.get('forwarded', 0) == 0 and \
                    st.get('errors', 0) >= 60 and st['status'] == 'active':
                st['status'] = 'restricted'
                save_json(PROG, prog)
                print(f'RESTRICTED_GUESS {key}', flush=True)
    finally:
        save_json(PROG, prog)
        save_media_index()
        try:
            await client.disconnect()
        except Exception:
            pass
    print(json.dumps(report(prog, run_fwd), ensure_ascii=False), flush=True)
    sys.exit(0)


if __name__ == '__main__':
    asyncio.run(amain())
