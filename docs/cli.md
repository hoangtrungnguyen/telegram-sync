# CLI reference

```
telesync {login,list,channels,sync,watch} [options]
```

All examples assume `uv run` in front, from the project directory.

## Shared options

Available on every command (and on `channels add|rm|ls`, not on `channels`
itself).

| flag | env var | description |
|---|---|---|
| `-c, --channel REF` | `TELEGRAM_CHANNELS` | channel to act on; repeatable. Overrides the saved list entirely |
| `-o, --out DIR` | `TELESYNC_OUT_DIR` | output folder (default `./vault`) |
| `--env-file PATH` | — | load a specific `.env` instead of the nearest one |
| `--session PATH` | `TELEGRAM_SESSION` | session file location |
| `--bot-token TOKEN` | `TELEGRAM_BOT_TOKEN` | log in as a bot instead of a user |
| `--layout per-message\|per-day` | `TELESYNC_LAYOUT` | one file per message, or one per day |
| `--media` | `TELESYNC_MEDIA` | download attachments into `assets/` |
| `--recheck N` | `TELESYNC_RECHECK` | also re-render the last N messages, to catch edits |
| `--no-react` | `TELESYNC_REACT=false` | don't react to synced messages |
| `--react-emoji X` | `TELESYNC_REACT_EMOJI` | reaction to use (default 🦄) |
| `--folder-format TPL` | `TELESYNC_FOLDER_FORMAT` | folder template, may nest with `/` |
| `--filename-format TPL` | `TELESYNC_FILENAME_FORMAT` | note filename template |
| `--dayfile-format TPL` | `TELESYNC_DAYFILE_FORMAT` | filename template for `--layout per-day` |

A `REF` is an `@username`, a `https://t.me/name` link, a numeric id
(`-1001234567890`), or the channel's display name as shown in the app.

## `telesync login`

Authorise this machine. Interactive for a user login (phone number → code → 2FA
password if set); instant for a bot token, where it only verifies the token and
prints the bot's username.

Writes a session file so later runs are non-interactive. Bot and user sessions
are kept in separate files.

## `telesync list`

Print the channels and groups you can sync, one per line: kind, handle, title.

Bot tokens cannot enumerate chats. In bot-only mode this instead shows whichever
chats appear in the pending update queue; in bot+MTProto mode it refuses and
tells you to add channels by numeric id.

## `telesync channels`

Manage the saved channel list, which lives in `.telesync-state.json` in the
output folder.

```bash
telesync channels add @durov "My Notes"    # verifies access, then saves
telesync channels add 1234567890 --no-verify
telesync channels rm @durov                # case-insensitive, @ optional
telesync channels ls
```

`add` resolves each ref before saving so typos fail immediately rather than at
sync time, and stores the canonical form (`@username`, else the numeric id) so
later runs don't have to search your dialog list again. `--no-verify` skips the
check and saves the ref verbatim.

## `telesync sync`

Fetch new messages once and exit.

| flag | description |
|---|---|
| `--full` | ignore saved state and re-sync from the first message |
| `--limit N` | only the newest N messages |

Incremental by default: it resumes from the highest message id already written
for that channel. See [sync-model.md](sync-model.md).

`--full` is rejected in bot-only mode, where no history exists to re-read.

## `telesync watch`

Backfill, then stay connected and write messages as they arrive. Also picks up
edits live. Ctrl-C to stop.

| flag | description |
|---|---|
| `--limit N` | cap the initial backfill |
| `--no-backfill` | skip the backfill, go straight to live |

In bot-only mode this long-polls `getUpdates` instead of holding an MTProto
connection.

## Exit codes

| code | meaning |
|---|---|
| `0` | success |
| `1` | runtime failure — auth, network, or at least one channel failed |
| `2` | configuration or usage error (missing credentials, no channels, bad template) |
| `130` | interrupted with Ctrl-C |

Useful for cron: a non-zero status means the run needs attention.
