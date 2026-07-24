# tele-sync

Sync messages from Telegram channels into a folder of Markdown files —
Obsidian-friendly: YAML frontmatter, CommonMark body, relative media links.

Every synced message gets a 🦄 reaction in Telegram, so you can see at a glance
what has been archived (`--no-react` to turn that off).

```bash
uv sync
cp .env.example .env          # credentials
uv run telesync login
uv run telesync channels add @durov
uv run telesync sync
```

```
vault/
└── pavel-durov/
    └── 2026-07-24-1430-1234-hello-world.md
```

```markdown
---
id: 1234
channel: Pavel Durov
date: '2026-07-24T14:30:00+07:00'
source: telegram
url: https://t.me/durov/1234
---

Hello **world**
```

## Features

- **Full history or live** — archive a channel from its first post, or keep
  `watch` running and write messages as they arrive.
- **Two login modes** — a user login (full history, any channel you can see) or
  a bot token (live only; works with nothing but the token).
- **Configurable naming** — `--folder-format '{channel}/{year}/{month}'`,
  `--filename-format '{id} - {title}'`, 17 placeholders plus strftime.
- **Faithful conversion** — bold, italic, code, links, spoilers, blockquotes,
  polls, locations; UTF-16 offsets handled so emoji never shift the markup.
- **Incremental** — resumes from a high-water mark per channel; `--recheck N`
  picks up edits.
- **One file per message, or per day** — day files merge on re-run instead of
  being overwritten.
- **Optional media download** into `assets/`, linked from the note.

## Commands

```bash
telesync login              # authorise this machine
telesync list               # channels you can sync
telesync channels add|rm|ls # manage the saved channel list
telesync sync               # pull new messages once
telesync watch              # stay connected for live updates
```

Channels can be given as `@username`, a `t.me` link, a numeric id, or the
channel's display name.

## Documentation

Full docs in [`docs/`](docs/README.md):

| | |
|---|---|
| [getting-started](docs/getting-started.md) | install, credentials, first sync |
| [login-modes](docs/login-modes.md) | user vs bot, and what each can do |
| [cli](docs/cli.md) | every command and flag |
| [configuration](docs/configuration.md) | `.env` keys, precedence, defaults |
| [naming](docs/naming.md) | folder and filename templates |
| [output](docs/output.md) | Markdown layout, frontmatter, media |
| [sync-model](docs/sync-model.md) | state, edits, reactions, rate limits |
| [automation](docs/automation.md) | cron and systemd |
| [troubleshooting](docs/troubleshooting.md) | errors and what they mean |
| [architecture](docs/architecture.md) | module map, for contributors |

## Requirements

Python 3.10+. Telethon, python-dotenv, PyYAML. `api_id`/`api_hash` from
<https://my.telegram.org>, or a bot token from
[@BotFather](https://t.me/botfather).

## Development

```bash
uv sync --group dev
uv run pytest -q          # 47 tests, no network required
```

## Security

`.env` and `*.session` are live credentials and are gitignored. A session file
is enough to act as you; a bot token is enough to act as the bot. Revoke a
leaked session in *Telegram → Settings → Devices*, or regenerate a token with
@BotFather.
