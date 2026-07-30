"""Authentication helpers — credentials from env or interactive prompt."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Credentials:
    api_id: int
    api_hash: str
    phone: str | None = None


def get_credentials_from_env() -> Credentials | None:
    """Read credentials from environment variables. Returns None if missing."""
    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    phone = os.environ.get("TG_PHONE", "").strip() or None
    if not api_id or not api_hash:
        return None
    try:
        return Credentials(api_id=int(api_id), api_hash=api_hash, phone=phone)
    except ValueError:
        return None


def prompt_credentials() -> Credentials:
    """Interactive prompt for credentials (CLI fallback)."""
    print("\n" + "=" * 50)
    print("  Telegram Tools — Credential Setup")
    print("=" * 50)
    print("  Get API_ID and API_HASH from:")
    print("  https://my.telegram.org/apps")
    print("=" * 50 + "\n")

    while True:
        try:
            val = input("  API_ID: ").strip()
            if val:
                api_id = int(val)
                break
        except ValueError:
            print("  API_ID must be a number.")

    while True:
        api_hash = input("  API_HASH: ").strip()
        if api_hash and len(api_hash) >= 10:
            break
        print("  Invalid API_HASH (must be at least 10 chars).")

    phone = input("  Phone (e.g. +963XXXXXXXXX, blank=skip): ").strip()
    return Credentials(api_id=api_id, api_hash=api_hash, phone=phone or None)
