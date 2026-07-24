# Getting started

## 1. Install

```bash
cd tele-sync
uv sync                     # or: python -m venv .venv && .venv/bin/pip install -e .
```

Python 3.10+. Runtime dependencies are Telethon, python-dotenv and PyYAML.

## 2. Get credentials

Pick one, depending on what you need — see [login-modes.md](login-modes.md) for
the full comparison.

**User login (recommended).** Reads any channel you can see in the app, with
full history. Go to <https://my.telegram.org> → *API development tools* → create
an application. Copy `api_id` and `api_hash`.

**Bot token.** Live messages only, no history, and the bot must be an admin of
the channel. Get one from [@BotFather](https://t.me/botfather).

## 3. Configure

```bash
cp .env.example .env
```

Fill in what you have:

```ini
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
# or, instead:
TELEGRAM_BOT_TOKEN=123456:AA...
```

`.env` is gitignored. Keep it that way — these are live credentials.

## 4. Log in

```bash
uv run telesync login
```

A user login asks for your phone number, then the code Telegram sends you (and
your 2FA password if you have one). It writes `telesync.session`, which keeps
you logged in — treat that file as a credential too.

A bot token needs no interaction; `login` just verifies the token works.

## 5. Choose channels

```bash
uv run telesync list                        # what can I see?
uv run telesync channels add @durov
uv run telesync channels add "My Notes"     # display names work too
uv run telesync channels ls
```

## 6. Sync

```bash
uv run telesync sync              # incremental; run it as often as you like
uv run telesync sync --full       # re-fetch the entire history
uv run telesync watch             # stay connected, write messages as they arrive
```

Output lands in `./vault` by default:

```
vault/
├── .telesync-state.json
└── pavel-durov/
    └── 2026-07-24-1430-1234-hello-world.md
```

## Next

- Change where files go and what they're called → [naming.md](naming.md)
- Run it unattended → [automation.md](automation.md)
- Something broke → [troubleshooting.md](troubleshooting.md)
