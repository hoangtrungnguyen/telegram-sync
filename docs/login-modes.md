# Login modes

tele-sync can talk to Telegram three ways. The mode is chosen automatically from
the credentials you supply.

| | **user** | **bot + MTProto** | **bot only** |
|---|---|---|---|
| credentials | `api_id`, `api_hash`, phone | `api_id`, `api_hash`, bot token | bot token |
| transport | MTProto (Telethon) | MTProto (Telethon) | HTTP Bot API |
| history backfill | ✅ full | ⚠️ id-range scan | ❌ none |
| live sync (`watch`) | ✅ | ✅ | ✅ |
| `telesync list` | ✅ all dialogs | ❌ | ⚠️ chats seen in the update queue |
| resolve `@username` | ✅ | ❌ numeric id only | ✅ via `getChat` |
| resolve display name | ✅ | ❌ | ❌ |
| needs channel admin | ❌ | ✅ | ✅ |

Mode selection, from `Config.mode`:

```
bot token + api_id/api_hash  ->  bot-mtproto
bot token alone              ->  bot-api
no bot token                 ->  user
```

## User login

The recommended mode. You are the client, so anything visible to you in the
Telegram app is readable — public channels, private channels you have joined,
groups, saved messages. `iter_messages` walks real history, so `--full` archives
a channel from its first post.

Session state lives in `telesync.session`. It is a bearer credential: anyone
with that file is logged in as you. It is gitignored.

## Bot + MTProto

A bot token used over MTProto. Telegram forbids bots from `messages.getHistory`,
but *does* allow fetching messages by explicit id, so backfill is emulated:
walk ids forward in batches of 100 from the last sync point, stop after 300
consecutive missing ids.

That heuristic is honest but imperfect — a channel with a gap of more than 300
deleted posts in a row stops early. Re-run `sync` to continue past it, or use a
user login for archival work.

Sessions are stored separately (`telesync-bot.session`) because a bot and a user
cannot share one.

## Bot only (HTTP Bot API)

A bot token with no `api_id`/`api_hash`. MTProto is unavailable, so tele-sync
talks to `api.telegram.org` over plain HTTP instead (stdlib only, no extra
dependency) and adapts the JSON into Telethon-shaped objects so the renderer and
writers are unchanged.

The hard limits come from Telegram, not from tele-sync:

- **No history.** The Bot API only exposes an update *queue*. Messages posted
  before the bot became an admin are unreachable; so are messages older than
  ~24h.
- **The queue is consumed.** Confirming an update deletes it server-side.
  tele-sync stores the confirmation offset in `.telesync-state.json`
  (`bot_api_offset`) so restarts don't reprocess, but a message read once cannot
  be read again.
- **One poller at a time.** `getUpdates` is exclusive and fails if a webhook is
  set for the bot.
- **Admin required.** A bot that is not an admin of a channel receives nothing.

Use this mode to capture new posts going forward. To archive what already
exists, add `api_id`/`api_hash`.
