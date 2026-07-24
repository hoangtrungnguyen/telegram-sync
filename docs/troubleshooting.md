# Troubleshooting

## `Config error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set`

No credentials found. Either create `.env` from `.env.example` and fill in the
values from <https://my.telegram.org>, or set `TELEGRAM_BOT_TOKEN` to run in bot
mode. If `.env` exists but is ignored, check you are running from the project
directory or pass `--env-file`.

## `Not logged in. Run: telesync login`

The session file is missing or was invalidated — for example by terminating the
session from *Telegram → Settings → Devices*. Run `telesync login` again.

## `No channels configured`

Nothing to sync. Add one:

```bash
telesync channels add @durov
telesync sync -c @durov          # or one-shot
```

## `no chat named 'X' — check telesync list for the exact name`

Name lookup searches your dialog list. It fails if you have not joined the
channel, or the name differs. Run `telesync list` and copy the handle, or use
the numeric id.

## `'X' is ambiguous: …`

Several chats matched that name fragment. Use the `@username` or numeric id
shown in the error.

## `bots cannot resolve names or @usernames — use the numeric channel id`

Bot mode over MTProto cannot resolve names. Get the numeric id (forward a post
to a bot like @userinfobot, or read it from `telesync list` under a user login)
and use the `-100…` form.

## `cannot find <username>` / `Cannot find any entity corresponding to …`

Telethon can only resolve entities you have some relationship with. Join the
channel first, or use the numeric id. For a public channel, make sure the
username is spelled exactly as in the link.

## Bot mode: `sync` writes 0 files

Expected once the queue is drained. The HTTP Bot API exposes no history — only
messages that arrive while the bot is an admin, and only until you read them.
See [login-modes.md](login-modes.md). For an archive of existing posts, add
`api_id`/`api_hash` and log in as yourself.

Also check: is the bot actually an admin of the channel? Bots receive nothing
from channels they don't administer.

## Bot mode: `Conflict: terminated by other getUpdates request`

Two things are polling the same bot. Stop the other `watch`/`sync`, or the other
program using that token. If you have a webhook configured for the bot,
`getUpdates` will not work at all until it is removed.

## `reactions disabled for this run (…)`

The channel rejected the reaction — most channels allow only a specific emoji
set, and some disable reactions entirely. Archiving continues normally. Pick an
allowed emoji with `--react-emoji`, or turn it off with `--no-react`.

## Sync is very slow / seems stuck

Telethon obeys Telegram's flood-waits by sleeping, which can be minutes on a
large `--full` run. It is working. Reduce pressure with `--no-react`, and don't
run two syncs against one session.

## Files reappear with different names after an edit

Your filename template has no `{id}`, so the old note cannot be located and
replaced. Add `{id}` — see [naming.md](naming.md).

## Text formatting looks wrong around emoji

Should not happen — offsets are handled in UTF-16 as Telegram specifies. If you
hit a case where it does, the message text and its entity list reproduce it;
that is worth an issue.

## Deleted messages still have files

By design; the archive is append-only. Remove the note yourself.

## Starting over

```bash
rm vault/.telesync-state.json    # re-sync everything next run
rm telesync.session              # force a fresh login
```

Deleting state does not delete notes, and re-syncing overwrites rather than
duplicates.
