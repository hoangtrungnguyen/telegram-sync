# Running it unattended

Two shapes: poll on a schedule with `sync`, or hold a connection with `watch`.
Both need a session that is already authorised — run `telesync login` once,
interactively, first.

## cron

```cron
*/15 * * * * cd /home/you/tele-sync && /home/you/.local/bin/uv run telesync sync >> sync.log 2>&1
```

Notes:

- cron has almost no environment — use absolute paths for both `uv` and the
  project directory.
- `sync` exits non-zero when something failed (see exit codes in
  [cli.md](cli.md)), so a wrapper can alert on failure.
- Overlapping runs share a session file and will fight. If a sync can take
  longer than the interval, wrap it: `flock -n /tmp/telesync.lock uv run telesync sync`.

## systemd timer

`~/.config/systemd/user/telesync.service`:

```ini
[Unit]
Description=Sync Telegram channels to Markdown

[Service]
Type=oneshot
WorkingDirectory=%h/tele-sync
ExecStart=%h/.local/bin/uv run telesync sync
```

`~/.config/systemd/user/telesync.timer`:

```ini
[Unit]
Description=Run telesync every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now telesync.timer
systemctl --user list-timers telesync.timer
journalctl --user -u telesync.service -f
```

`Persistent=true` catches up on a run missed while the machine was asleep.

## Long-running watch

For near-instant syncing, keep `watch` alive instead of polling:

```ini
[Unit]
Description=Watch Telegram channels
After=network-online.target

[Service]
WorkingDirectory=%h/tele-sync
ExecStart=%h/.local/bin/uv run telesync watch
Restart=always
RestartSec=30

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now telesync-watch.service
```

`watch` backfills on start, so a restart after downtime does not lose messages —
except in bot-only mode, where the update queue expires after ~24h.

Don't run `watch` and a `sync` timer against the same output folder at the same
time: two processes writing one state file will clobber each other's high-water
marks, and in bot-only mode they will fight over the `getUpdates` lock.

## Keeping an eye on it

```bash
jq '.channels' vault/.telesync-state.json     # last_id and last_sync per channel
find vault -name '*.md' -newermt '-1 day' | wc -l
```

A `last_sync` that stops advancing means the run is failing — check the log, then
[troubleshooting.md](troubleshooting.md).
