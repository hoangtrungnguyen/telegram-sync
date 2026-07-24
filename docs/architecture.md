# Architecture

For contributors. ~1000 lines of Python, no framework.

## Modules

```
telesync/
├── cli.py       argparse, command dispatch, wiring
├── config.py    Config dataclass; env + flags -> validated settings
├── state.py     .telesync-state.json: high-water marks, subscriptions
├── render.py    Telegram message -> Markdown; name templates
├── sync.py      MTProto sync loop, file writers, Reactor
├── botapi.py    HTTP Bot API transport + Telethon-shaped adapters
└── botsync.py   getUpdates polling loop
```

Dependency direction is one-way: `cli` → {`botsync`, `sync`, `config`} →
{`botapi`, `render`, `state`}. `render` imports nothing from the project, which
is why it is the easiest place to test.

## Flow

```
cli.main
  └─ load_config            validate credentials + templates, fail fast
  └─ make_client            TelegramClient, or BotAPI shim
  └─ resolve_channel_refs   -c flag > saved list + env
  │
  ├─ MTProto:  sync_channel ──> _iter_user_messages   (getHistory)
  │                         └─> _iter_bot_messages    (id-range scan)
  │                              └─ write_message
  └─ Bot API:  run_updates  ──> getUpdates long-poll
                                └─ adapt_message ─> write_message

write_message
  ├─ author_of              post signature, else sender
  ├─ download_media         optional, into assets/
  ├─ channel_folder         folder template
  ├─ write_per_message      filename template, replace stale note by id
  │  or write_per_day       merge into the day file by <!-- telesync:ID -->
  └─ Reactor.react          🦄, best effort
```

## The two transports

The interesting design constraint: a bot token alone cannot use MTProto, and the
HTTP Bot API returns a completely different JSON shape.

Rather than fork the renderer, `botapi.adapt_message` converts Bot API JSON into
an object exposing the same attributes Telethon's `Message` does — `.message`,
`.entities` (real `telethon.tl.types` entity objects), `.date`, `.photo`,
`.poll`, an async `.get_sender()` — and `BotAPI` itself duck-types the few
client methods the writers call (`download_media`, `is_bot`, `get_entity`). So
`render.py` and the writers never learn which transport they are on.

`adapt_chat` also normalises ids: the Bot API reports channels as
`-1001234567890`, MTProto as `1234567890`. tele-sync stores the bare form so
state keys match across modes, keeping the prefixed form in `bot_api_id` for
outgoing HTTP calls.

`Reactor` branches on `hasattr(client, "set_reaction")` — the one place the two
transports genuinely differ in behaviour rather than shape.

## Entity conversion

`render.entities_to_markdown` is the fiddly part. Telegram sends offsets in
**UTF-16 code units**, so the text is encoded to `utf-16-le` and sliced there
before decoding back — a naive `str` index misplaces markup after any emoji.

Spans become open/close marker events sorted by `(position, close-before-open,
length)`, so nested and adjacent entities nest correctly. Blockquotes cannot be
expressed by wrapping a span, so they emit sentinels that a second pass turns
into `> ` line prefixes.

## Testing

```bash
uv run pytest -q
```

47 tests, no network. Telegram objects are `SimpleNamespace` fakes; `FakeClient`
and `FakeBotAPI` stand in for the transports. The suite covers entity conversion
(including UTF-16 offsets and nesting), name templates and their sanitisation,
per-day merging, ref resolution, config precedence, the Bot API adapters, and
the reactor's failure behaviour.

## Adding things

**A new frontmatter field** — `render.build_frontmatter`. Keys with `None`
values are dropped automatically.

**A new media type** — `render.media_kind` for the label, `botapi.adapt_message`
for the Bot API side.

**A new placeholder** — add it to `render.build_context` and `PLACEHOLDERS`.
Validation and `--help` pick it up from there.

**A new command** — a subparser in `cli.build_parser` with `parents=[common]`,
plus a `cmd_*` coroutine and a branch in `main`. Note that common flags belong
on leaf parsers only: argparse lets a subparser's defaults overwrite values its
parent already parsed.
