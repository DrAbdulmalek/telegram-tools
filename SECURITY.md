# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | ✅ Active support  |
| < 1.0   | ❌ Not supported   |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it **privately**:

1. Go to [Security Advisories](https://github.com/DrAbdulmalek/telegram-tools/security/advisories/new)
2. Click **"Report a vulnerability"**
3. Provide a clear description and proof of concept
4. Do NOT open a public issue for security-related matters

You should receive a response within 48 hours. If the vulnerability is confirmed:
- A fix will be prepared in a private branch
- A patch release will be published as soon as possible
- You will be credited in the release notes (unless you prefer to remain anonymous)

## Security Considerations

### Credentials

This project handles sensitive Telegram credentials:

- **API ID** and **API Hash** — from [my.telegram.org](https://my.telegram.org)
- **Session files** (`.session`) — contain the auth key, equivalent to a login
- **SESSION_STRING** — exported session, equivalent to a login

**Never commit any of these to Git.** The `.gitignore` file excludes:

- `*.session` and `*.session-journal`
- `.env` and `.env.local`
- `copier_progress.json` (may contain message IDs)

### Best Practices for Users

1. **Use environment variables** — never hardcode credentials in scripts
2. **Use HF Secrets** when deploying to HuggingFace Spaces
3. **Export SESSION_STRING** via the `tg-tools login` command, then save it as a Secret
4. **Clear your terminal** after running `tg-tools login` (the string is printed to stdout)
5. **Revoke API apps** at my.telegram.org when no longer needed
6. **Use 2FA** on your Telegram account

### Best Practices for Contributors

1. **Never commit** credentials, session files, or test outputs that contain real data
2. **Use `detect-private-key`** pre-commit hook (already configured)
3. **Run `bandit -r src/`** before submitting PRs (configured in CI)
4. **Sanitize test fixtures** — use fake data, not real Telegram entities
5. **Review `.gitignore`** when adding new file types that might contain sensitive data

### Rate Limiting

The toolkit includes an adaptive `RateLimiter` to avoid Telegram bans:
- Base delay configurable per operation
- Exponential backoff on `FloodWaitError` (doubles, capped at 60s)
- Relaxation after 10 consecutive successes

**Users must still use sensible delays** (≥ 2 seconds recommended) to avoid account bans.

### Disclaimer

This tool is for educational purposes only. Misuse may violate Telegram's Terms of Service.
The authors are not responsible for any account bans or legal consequences resulting from use.
