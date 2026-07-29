# Sync model

## State

`<out-dir>/.telesync-state.json` holds everything tele-sync remembers:

```json
{
  "channels": {
    "1006503122": {
      "last_id": 1234,
      "title": "Pavel Durov",
      "ref": "@durov",
      "folder": "pavel-durov",
      "last_sync": "2026-07-24T07:30:00+00:00"
    }
  },
  "subscriptions": ["@durov"],
  "bot_api_offset": 480512345
}
```

- **`channels`** — keyed by channel id, so a channel that gets renamed keeps its
  history. `last_id` is the high-water mark: the next sync starts above it.
- **`subscriptions`** — the list managed by `telesync channels add|rm`.
- **`bot_api_offset`** — only in bot-only mode; the `getUpdates` confirmation
  offset, so a restart doesn't reprocess the queue.

The file is written atomically (temp file, then rename), so an interrupted run
cannot corrupt it. Deleting it makes the next sync re-fetch everything, which is
safe: existing notes are overwritten, not duplicated.

## Incremental runs

`sync` fetches only messages newer than `last_id` for that channel. That makes a
repeated run cheap — a cron job every 15 minutes costs one round trip when
nothing new has been posted.

`--full` ignores `last_id` and walks the channel from the beginning. Existing
files are rewritten in place.

`--limit N` fetches the newest N messages instead, walking backwards.

## Edits

Telegram offers no "everything changed since X" feed for old posts, so an edit
to a message you already synced is invisible to a plain incremental run.

Two ways to catch them:

- **`--recheck N`** — start the run N messages below the high-water mark, so the
  last N notes are re-rendered every time. `TELESYNC_RECHECK=20` is a cheap
  default for a busy channel.
- **`watch`** — subscribes to `MessageEdited` (or receives
  `edited_channel_post` in bot-only mode) and rewrites the note immediately.

Re-rendering is idempotent: the same message produces the same file. See
[naming.md](naming.md) for why `{id}` in the filename template matters when an
edit changes the title.

## Deletions

Not propagated. A message deleted in Telegram keeps its Markdown file — the
archive is append-only by design. Delete the note yourself if you want it gone.

## Reactions

Every message written gets a 🦄 reaction in Telegram, which doubles as a visible
"archived" marker in the chat. A message re-synced after an edit gets 👾
instead, so you can tell an updated note from a first sync at a glance.

```bash
telesync sync --no-react           # off for this run
telesync sync --react-emoji 👍     # something else
telesync sync --react-edit-emoji 🔁   # different edit marker
TELESYNC_REACT=false               # off by default
```

Reactions are best effort. Channels can restrict which emoji are allowed, and
reacting is rate limited; the first failure prints one warning, disables
reactions for the rest of the run, and lets the sync continue. Reacting is never
allowed to break archiving.

Consider `--no-react` for a large `--full` backfill — one reaction per message
across thousands of posts is a good way to meet a flood-wait.

## React to sync

The marker also works in the other direction: while `watch` is running, reacting
to a message in Telegram — any emoji, however old the message — writes (or
rewrites) its note immediately. Handy for pulling a single old post into the
archive without a `--full` run, or for re-rendering one message after an edit.

Requires an MTProto session (`TELEGRAM_API_ID`/`TELEGRAM_API_HASH`); the HTTP
Bot API reports *that* a reaction happened but offers no way to fetch the
message it landed on, so in bot-only mode `watch` prints a pointer instead.
With a bot session the bot must be an admin of the chat to receive reaction
updates, and the Reactor's own 🦄 is ignored so a write cannot re-trigger
itself.

## Rate limits

Telethon handles Telegram's flood-waits by sleeping for the requested time, so a
large sync is slow rather than failing. Let it run; don't parallelise it across
processes with the same session.
