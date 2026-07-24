# tele-sync documentation

Sync messages from Telegram channels into a folder of Markdown files.

| doc | what's in it |
|---|---|
| [getting-started.md](getting-started.md) | install, credentials, first sync |
| [login-modes.md](login-modes.md) | user vs bot login, and what each can do |
| [cli.md](cli.md) | every command and flag |
| [configuration.md](configuration.md) | `.env` keys, precedence, defaults |
| [naming.md](naming.md) | folder and filename templates |
| [output.md](output.md) | Markdown layout, frontmatter, media |
| [sync-model.md](sync-model.md) | incremental state, edits, reactions |
| [automation.md](automation.md) | cron and systemd |
| [troubleshooting.md](troubleshooting.md) | errors and what they mean |
| [architecture.md](architecture.md) | module map, for contributors |

## In one minute

```bash
uv sync
cp .env.example .env          # add credentials
uv run telesync login
uv run telesync channels add @durov
uv run telesync sync
```

Each synced message becomes one Markdown file with YAML frontmatter, and gets a
🦄 reaction in Telegram so you can see what has been archived.
