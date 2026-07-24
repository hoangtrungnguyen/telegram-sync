# Configuration

## Precedence

For every setting, highest wins:

1. command-line flag
2. environment variable (including anything in `.env`)
3. built-in default

`.env` is read from the current directory unless `--env-file` points elsewhere.
Real environment variables already set in the shell are **not** overwritten by
`.env`.

Channels are the one exception, because the saved list is a third source:

1. `-c/--channel` — if given at all, it is used exclusively
2. otherwise: saved list (`telesync channels add`) **plus** `TELEGRAM_CHANNELS`,
   deduplicated, saved entries first

## Environment variables

### Credentials

| variable | description |
|---|---|
| `TELEGRAM_API_ID` | numeric app id from <https://my.telegram.org> |
| `TELEGRAM_API_HASH` | app hash from the same page |
| `TELEGRAM_BOT_TOKEN` | bot token from @BotFather; enables bot mode |
| `TELEGRAM_SESSION` | session file path (default `./telesync.session`, or `./telesync-bot.session` in bot mode) |

You need either `api_id` + `api_hash`, or a bot token, or both. See
[login-modes.md](login-modes.md).

### What to sync

| variable | default | description |
|---|---|---|
| `TELEGRAM_CHANNELS` | — | comma- or newline-separated refs |
| `TELESYNC_OUT_DIR` | `./vault` | output folder |
| `TELESYNC_RECHECK` | `0` | re-render the last N messages each run, to catch edits |

### How to write it

| variable | default | description |
|---|---|---|
| `TELESYNC_LAYOUT` | `per-message` | `per-message` or `per-day` |
| `TELESYNC_FOLDER_FORMAT` | `{channel}` | folder template, may nest with `/` |
| `TELESYNC_FILENAME_FORMAT` | `{date}-{time}-{id}-{slug}` | note filename template |
| `TELESYNC_DAYFILE_FORMAT` | `{date}` | filename template for `per-day` |
| `TELESYNC_MEDIA` | `false` | download attachments |
| `TELESYNC_MEDIA_DIR` | `assets` | subfolder for downloads |

Templates are documented in [naming.md](naming.md) and validated at startup.

### Reactions

| variable | default | description |
|---|---|---|
| `TELESYNC_REACT` | `true` | react to each synced message |
| `TELESYNC_REACT_EMOJI` | `🦄` | which emoji to use |

Booleans accept `1/true/yes/on` (case-insensitive); anything else is false.

## Example `.env`

```ini
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef

TELEGRAM_CHANNELS=@durov,@telegram
TELESYNC_OUT_DIR=~/Obsidian/Telegram

TELESYNC_FOLDER_FORMAT={channel}/{year}
TELESYNC_FILENAME_FORMAT={date} {title}
TELESYNC_MEDIA=true
TELESYNC_RECHECK=20
```

## Secrets

`.env` and `*.session` are live credentials and are gitignored. A session file
is enough to act as you; a bot token is enough to act as the bot. If either
leaks, revoke it: terminate the session in Telegram → *Settings → Devices*, or
regenerate the token with @BotFather.
