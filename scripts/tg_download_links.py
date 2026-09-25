#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_download_links.py — download book/file links harvested from source channels
(state/forward/file_links.json) into download/link_harvest/, and append
manifest entries compatible with tg_send_books.py.

Order: keyword-relevant first, then class priority direct > archive > drive
> mediafire > others. Size cap 250MB. Persisted done/failed state.
Usage: DL_BUDGET=110 python3 tg_download_links.py
"""
import os, re, json, time, sys, requests
from urllib.parse import urlparse, parse_qs, unquote

BASE = '/home/z/my-project'
LINKS = f'{BASE}/state/forward/file_links.json'
STATE = f'{BASE}/state/forward/link_dl_state.json'
HARVEST = f'{BASE}/download/link_harvest'
MANIFEST = f'{BASE}/download/translation-books/manifest.json'

MAX_BYTES = 250 * 1024 * 1024
SOFT = float(os.environ.get('DL_BUDGET', '110'))
T0 = time.time()
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}


def left():
    return SOFT - (time.time() - T0)


def load_json(p, d):
    try:
        return json.load(open(p))
    except Exception:
        return d


def save_json(p, o):
    tmp = p + '.tmp'
    json.dump(o, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, p)


def priority_class(u):
    h = urlparse(u).netloc.lower()
    if 'archive.org' in h:
        return 1
    if 'drive.google.com' in h or 'docs.google.com' in h:
        return 2
    if 'mediafire.com' in h:
        return 3
    if 'mega.nz' in h or 'scribd' in h or '4shared' in h:
        return 9  # hard hosts — skip for now
    if u.lower().split('?')[0].endswith(('.zip', '.rar', '.7z', '.pdf', '.epub', '.mobi', '.djvu', '.doc', '.docx', '.tar', '.gz')):
        return 0  # plain direct file
    return 4  # page hosts (bookleaks, universities, gov...)


def _fix_moji(s):
    """Repair UTF-8 misdecoded as latin-1 (common with HTTP headers)."""
    if 'Ø' in s or 'Ù' in s or 'Û' in s:
        try:
            return s.encode('latin-1').decode('utf-8', errors='replace')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return s
    return s


def fname_from_headers(cd, url):
    if cd:
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
        if m:
            return _fix_moji(unquote(m.group(1)))
        m = re.search(r'filename="?([^";\n]+)"?', cd)
        if m:
            return _fix_moji(m.group(1).strip())
    return _fix_moji(unquote(os.path.basename(urlparse(url).path))) or 'file'


def safe_name(s, src):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]', '_', s)[:120] or 'file'
    return f'{src}__{s}'


def try_download(url, dest_path):
    """Stream-download; returns (ok, size, final_name_or_err)."""
    try:
        with requests.get(url, headers=UA, stream=True, timeout=(20, 90), allow_redirects=True) as r:
            if r.status_code != 200:
                return False, 0, f'http_{r.status_code}'
            ctype = r.headers.get('Content-Type', '').lower()
            if 'text/html' in ctype:
                return False, 0, 'html_not_file'
            cd = r.headers.get('Content-Disposition', '')
            name = fname_from_headers(cd, r.url)
            cl = r.headers.get('Content-Length')
            if cl and int(cl) > MAX_BYTES:
                return False, 0, 'too_large'
            n = 0
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(1 << 16):
                    n += len(chunk)
                    if n > MAX_BYTES:
                        f.close()
                        os.remove(dest_path)
                        return False, 0, 'too_large_stream'
                    f.write(chunk)
            return True, n, name
    except Exception as ex:
        return False, 0, f'{type(ex).__name__}: {str(ex)[:80]}'


def drive_direct_url(u):
    qid = parse_qs(urlparse(u).query).get('id', [None])[0]
    if not qid:
        m = re.search(r'/d/([A-Za-z0-9_-]{10,})', u)
        qid = m.group(1) if m else None
    if not qid:
        return None
    # usercontent endpoint with confirm=t bypasses the virus-scan interstitial
    return f'https://drive.usercontent.google.com/download?id={qid}&export=download&confirm=t'


def mediafire_direct_url(u):
    try:
        r = requests.get(u, headers=UA, timeout=(20, 60))
        m = re.search(r'href="(https?://download\d+\.mediafire\.com/[^"]+)"', r.text)
        return m.group(1) if m else None
    except Exception:
        return None


def main():
    os.makedirs(HARVEST, exist_ok=True)
    links = load_json(LINKS, {})
    st = load_json(STATE, {'done': [], 'failed': {}})
    done = set(st['done'])
    failed = st['failed']
    manifest = load_json(MANIFEST, [])
    mf_files = {m.get('file') for m in manifest}

    cands = [(v.get('kw', False), priority_class(u), u, v)
             for u, v in links.items() if u not in done and u not in failed]
    cands.sort(key=lambda x: (not x[0], x[1]))

    dl = 0
    for _, cls, u, meta in cands:
        if left() < 15:
            print('BUDGET_OUT', flush=True)
            break
        if cls == 9:
            failed[u] = 'unsupported_host'
            continue
        src = meta.get('src', 'x')
        url = u
        if cls == 2:
            url = drive_direct_url(u)
            if not url:
                failed[u] = 'drive_no_id'
                continue
        elif cls == 3:
            url = mediafire_direct_url(u)
            if not url:
                failed[u] = 'mediafire_no_link'
                continue
        tmp_dest = os.path.join(HARVEST, '_tmp_' + str(abs(hash(u)) % 10**8))
        ok, size, name = try_download(url, tmp_dest)
        if ok and size > 0:
            fname = safe_name(name, src)
            # dedupe basename
            if fname in mf_files or os.path.exists(os.path.join(HARVEST, fname)):
                base, ext = os.path.splitext(fname)
                fname = f'{base}_{abs(hash(u)) % 9999}{ext}'
            final = os.path.join(HARVEST, fname)
            os.replace(tmp_dest, final)
            manifest.append({'file': fname, 'size': size, 'downloaded': True,
                             'repo': src, 'path': name.lower(),
                             'title': (meta.get('text') or '')[:80], 'src_url': u})
            done.add(u)
            dl += 1
            print(f'OK [{src}] {fname} ({size/1e6:.2f}MB)', flush=True)
        else:
            failed[u] = name
            print(f'FAIL [{src}] {u[:70]} -> {name}', flush=True)
            try:
                os.remove(tmp_dest)
            except OSError:
                pass
        if len(done) % 5 == 0:
            save_json(STATE, {'done': sorted(done), 'failed': failed})
            save_json(MANIFEST, manifest)
        time.sleep(1.0)
    save_json(STATE, {'done': sorted(done), 'failed': failed})
    save_json(MANIFEST, manifest)
    print(json.dumps({'downloaded_this_run': dl, 'done_total': len(done),
                      'failed_total': len(failed), 'manifest_len': len(manifest)}), flush=True)


if __name__ == '__main__':
    main()
