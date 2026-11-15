# artifacts/

Deployment pieces for running this repo's watcher unattended on the Mac.

| file | purpose |
|---|---|
| `com.trungnguyenhoang.telesync-watch.plist` | launchd user agent: `uv run telesync watch` from this repo, started at login, restarted on exit |

## launchd agent

Set up 2026-11-15. The live copy is `~/Library/LaunchAgents/com.trungnguyenhoang.telesync-watch.plist`;
the one here is the tracked source. Edit here, then reinstall.

What it does:

- runs `/Users/trungnguyenhoang/.local/bin/uv run telesync watch` with `WorkingDirectory` = this repo
- `RunAtLoad` → starts at login; `KeepAlive` + `ThrottleInterval 30` → restarts ~30 s after any exit
- stdout + stderr → `watch.log` in this repo (gitignored)
- `PATH` is set explicitly because launchd gives almost no environment

### Install / reinstall

```bash
cp artifacts/com.trungnguyenhoang.telesync-watch.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/com.trungnguyenhoang.telesync-watch 2>/dev/null  # if already loaded
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.trungnguyenhoang.telesync-watch.plist
```

### Control

```bash
launchctl print gui/$(id -u)/com.trungnguyenhoang.telesync-watch | grep -E 'state|pid'   # status
launchctl kickstart -k gui/$(id -u)/com.trungnguyenhoang.telesync-watch                  # restart (after .env change)
launchctl bootout gui/$(id -u)/com.trungnguyenhoang.telesync-watch                       # stop for good
tail -f watch.log                                                                        # what it's doing
jq '.channels' vault/.telesync-state.json                                                # last_id / last_sync per chat
```

### Things to know

- **One watcher only.** The vault also has a clone at
  `~/Documents/Obsidian/tools/telegram-sync` with its own control script. Starting a watcher
  there while this agent is loaded makes two processes poll the same bot →
  `Conflict: terminated by other getUpdates`, and both lose messages.
- **Bot-token mode.** `.env` has only `TELEGRAM_BOT_TOKEN`; `TELEGRAM_API_ID/HASH` are empty.
  The bot receives a message only when it is posted or edited, and Telegram holds undelivered
  updates ~24 h. If the agent is down longer than that, those posts are gone for this mode;
  editing a post in Telegram re-delivers it. Backfill of older history needs a user login
  (`telesync login` with API id/hash).
- **Seeding and Engineer are basic groups, not channels.** They share one message-id counter
  (ids alternate between the two folders) and `t.me/c/...` links in the notes' frontmatter
  don't resolve.
- **macOS Documents permission** was verified: a launchd-run process can read and write
  `~/Documents/Obsidian/03-TheClock/1-Log/{Seeding,Engineer}`.
- Output lands in `vault/{seeding,engineer}` → symlinks into the Obsidian vault.
