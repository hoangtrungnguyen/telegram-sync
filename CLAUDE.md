# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync --group dev                 # install deps + dev tools
uv run pytest -q                    # full suite (47 tests, no network)
uv run pytest tests/test_render.py  # one file
uv run pytest tests/test_render.py::test_name   # one test
uv run telesync <command>           # run the CLI (login, list, channels, sync, watch)
```

No linter/formatter is configured. Credentials come from `.env` (copy `.env.example`); `.env` and `*.session` are live credentials — never commit or print them.

## Architecture

~1000 lines of Python, no framework. `docs/architecture.md` is the authoritative contributor doc — read it before structural changes. Key points:

- **Dependency direction is one-way**: `cli` → {`botsync`, `sync`, `config`} → {`botapi`, `render`, `state`}. `render.py` imports nothing from the project.
- **Two transports, one renderer.** MTProto (Telethon user/bot login, full history) vs HTTP Bot API (token only, live updates via getUpdates). `botapi.adapt_message` converts Bot API JSON into Telethon-`Message`-shaped objects (real `telethon.tl.types` entities), and `BotAPI` duck-types the client methods writers call — so `render.py` and the writers never know which transport they're on. `Reactor` branches on `hasattr(client, "set_reaction")`, the one real behavioural difference.
- **Channel id normalisation**: Bot API reports `-1001234567890`, MTProto `1234567890`. State stores the bare form so keys match across modes; the prefixed form lives in `bot_api_id` for HTTP calls.
- **Entity conversion** (`render.entities_to_markdown`): Telegram offsets are UTF-16 code units — text is sliced via `utf-16-le` encoding, never by `str` index (emoji would shift markup). Spans become open/close marker events; blockquotes use sentinels resolved in a second pass.
- **State**: `.telesync-state.json` holds per-channel high-water marks and subscriptions; sync is incremental and resumes from there.

## Extension points (from docs/architecture.md)

- New frontmatter field → `render.build_frontmatter` (None values auto-dropped).
- New media type → `render.media_kind` + `botapi.adapt_message`.
- New name-template placeholder → `render.build_context` + `PLACEHOLDERS` (validation and `--help` pick it up).
- New command → subparser in `cli.build_parser` with `parents=[common]`, a `cmd_*` coroutine, a branch in `main`. **Gotcha**: common flags belong on leaf parsers only — a subparser's defaults overwrite values its parent already parsed.

## Testing conventions

Tests use `SimpleNamespace` fakes for Telegram objects and `FakeClient`/`FakeBotAPI` for transports — no network, keep it that way. `pytest-asyncio` runs in `asyncio_mode = "auto"`, so async tests need no decorator.
