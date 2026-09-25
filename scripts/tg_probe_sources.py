#!/usr/bin/env python3
"""Probe source channels: resolve usernames, count messages, check noforwarding."""
import asyncio, json, sys
from telethon import TelegramClient, functions
from telethon.sessions import StringSession

BASE = '/home/z/my-project'
API = json.load(open(f'{BASE}/.secrets/telegram_api.json'))
SESSION = open(f'{BASE}/.secrets/tg_string_session.txt').read().strip()

PROBE = ['Angalizy1', 'xesarth', 'keymiftah_79', 'tarjamatbybasel',
         'translatorguide1', 'TranslationZF', 'translationve', 'pttranslators',
         'TransSkylanguagesolutions', 'Targma_amely', 'translationpolice',
         'maqhaalmutarjim_group', 'BonjourTranslation']

async def main():
    async with TelegramClient(StringSession(SESSION), API['api_id'], API['api_hash']) as c:
        for u in PROBE:
            try:
                e = await c.get_entity(u)
                full = await c(functions.channels.GetFullChannelRequest(e)) if hasattr(e, 'broadcast') or getattr(e, 'megagroup', False) else None
                nofwd = None
                title = getattr(e, 'title', '?')
                if full is not None:
                    nofwd = getattr(full.full_chat, 'noforwards', None)
                # count messages roughly via last message id
                last_id = 0
                async for m in c.iter_messages(e, limit=1):
                    last_id = m.id
                print(f"OK {u}: id={e.id} title={title!r} last_id={last_id} noforwards={nofwd}")
            except Exception as ex:
                print(f"FAIL {u}: {type(ex).__name__}: {ex}")
            await asyncio.sleep(1.5)

asyncio.run(main())
