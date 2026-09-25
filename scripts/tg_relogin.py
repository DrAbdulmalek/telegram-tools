#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tg_relogin.py — rebuild Telegram session after environment rollback.

Usage:
  python tg_relogin.py send          -> send login code to phone, persist phone_code_hash
  python tg_relogin.py code <CODE>   -> finish login, persist StringSession (never printed)

Never prints the session string or code hash. Prints status tokens only.
"""
import sys, json, asyncio
from telethon import TelegramClient, errors
from telethon.sessions import StringSession

BASE = '/home/z/my-project'
SEC = f'{BASE}/.secrets'
API = json.load(open(f'{SEC}/telegram_api.json'))
PHONE = API['phone']


async def main():
    if len(sys.argv) < 2:
        print('USAGE: send | code <CODE>')
        sys.exit(2)
    mode = sys.argv[1]
    client = TelegramClient(StringSession(), int(API['api_id']), API['api_hash'],
                            request_retries=2, retry_delay=1, connection_retries=2,
                            timeout=15)
    await client.connect()
    if not await client.is_user_authorized():
        if mode == 'send':
            sent = await client.send_code_request(PHONE)
            with open(f'{SEC}/tg_phone_code_hash.txt', 'w') as f:
                f.write(sent.phone_code_hash)
            print('CODE_SENT', flush=True)
        elif mode == 'code':
            pass  # fall through to sign_in block below using saved phone_code_hash
    else:
        if mode == 'send':
            with open(f'{SEC}/tg_string_session.txt', 'w') as f:
                f.write(StringSession(client.session).save())
            print('ALREADY_AUTH', flush=True)
        elif mode == 'code':
            with open(f'{SEC}/tg_string_session.txt', 'w') as f:
                f.write(StringSession(client.session).save())
            print('ALREADY_AUTH', flush=True)
    if mode == 'code' and not await client.is_user_authorized():
        code = sys.argv[2]
        h = open(f'{SEC}/tg_phone_code_hash.txt').read().strip()
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
        s = StringSession(client.session)
        with open(f'{SEC}/tg_string_session.txt', 'w') as f:
            f.write(s.save())
        me = await client.get_me()
        print('AUTH_OK', getattr(me, 'username', None) or getattr(me, 'first_name', ''),
              flush=True)
    await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
