#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_relogin2.py — Telegram re-login with PERSISTENT device session.

Root-cause fix: Telegram binds phone_code_hash to the auth context of the
session that requested it. The old script created a fresh StringSession per
invocation, so `code` always hit PHONE_CODE_EXPIRED. This script persists a
device .session file so `send` and `code` share one auth context.

Usage:
  python tg_relogin2.py send         -> request login code (persists hash+session)
  python tg_relogin2.py code <CODE>  -> finish login, write tg_string_session.txt

Never prints the session string or code hash. Status tokens only.
"""
import sys, json, asyncio
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

BASE = '/home/z/my-project'
SEC = f'{BASE}/.secrets'
DEV_SESSION = f'{SEC}/relogin_device.session'
API = json.load(open(f'{SEC}/telegram_api.json'))
PHONE = API['phone']


async def main():
    if len(sys.argv) < 2:
        print('USAGE: send | code <CODE>')
        sys.exit(2)
    mode = sys.argv[1]
    client = TelegramClient(DEV_SESSION, int(API['api_id']), API['api_hash'],
                            request_retries=2, retry_delay=1, connection_retries=2,
                            timeout=15)
    await client.connect()
    if not await client.is_user_authorized():
        if mode == 'send':
            sent = await client.send_code_request(PHONE)
            with open(f'{SEC}/tg_phone_code_hash.txt', 'w') as f:
                f.write(sent.phone_code_hash)
            print('CODE_SENT', flush=True)
        # mode == 'code' falls through to sign_in below
    else:
        s = StringSession.save(client.session)
        with open(f'{SEC}/tg_string_session.txt', 'w') as f:
            f.write(s)
        me = await client.get_me()
        print('ALREADY_AUTH', getattr(me, 'username', None) or getattr(me, 'first_name', ''),
              flush=True)
        await client.disconnect()
        return
    if mode == 'code':
        code = sys.argv[2]
        with open(f'{SEC}/tg_phone_code_hash.txt') as f:
            h = f.read().strip()
        try:
            await client.sign_in(phone=PHONE, code=code, phone_code_hash=h)
        except errors.SessionPasswordNeededError:
            print('PASSWORD_NEEDED', flush=True)
            sys.exit(5)
        except errors.PhoneCodeInvalidError:
            print('CODE_INVALID', flush=True)
            sys.exit(6)
        except errors.PhoneCodeExpiredError:
            print('CODE_EXPIRED (run send again)', flush=True)
            sys.exit(7)
        except errors.FloodWaitError as e:
            print(f'FLOOD_WAIT {e.seconds}', flush=True)
            sys.exit(8)
        s = StringSession.save(client.session)
        with open(f'{SEC}/tg_string_session.txt', 'w') as f:
            f.write(s)
        me = await client.get_me()
        print('AUTH_OK', getattr(me, 'username', None) or getattr(me, 'first_name', ''),
              flush=True)
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
