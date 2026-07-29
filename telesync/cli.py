"""Command line interface for telesync."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from telethon import TelegramClient, events, utils
from telethon.tl import types

from .botapi import BotAPI, BotAPIError, adapt_chat
from .botsync import run_updates
from .config import Config, ConfigError, LAYOUTS, load_config
from .render import DEFAULT_DAYFILE, DEFAULT_FILENAME, DEFAULT_FOLDER, PLACEHOLDERS
from .state import State
from .sync import (
    Reactor,
    channel_key,
    reaction_target,
    resolve_channel,
    sync_channel,
    write_message,
)

# How long after writing a note reaction updates for that message are ignored,
# so the Reactor's own 🦄 cannot re-trigger the write it marks.
REACTION_COOLDOWN = 60.0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", metavar="PATH", help="path to a .env file")
    common.add_argument("-o", "--out", metavar="DIR", help="output folder (default ./vault)")
    common.add_argument("--session", metavar="PATH", help="Telethon session file")
    common.add_argument(
        "--bot-token", metavar="TOKEN",
        help="log in as a bot instead of a user (bot must be an admin of the channel)",
    )
    common.add_argument(
        "-c", "--channel", action="append", metavar="REF",
        help="channel @username, t.me link, or id (repeatable; overrides saved list)",
    )
    common.add_argument("--layout", choices=LAYOUTS, help="one file per message or per day")
    common.add_argument("--media", action="store_true", help="download attachments")
    common.add_argument(
        "--recheck", type=int, metavar="N",
        help="also re-render the last N messages before the sync point (catches edits)",
    )
    common.add_argument(
        "--no-react", action="store_true",
        help="do not react to synced messages in Telegram",
    )
    common.add_argument(
        "--react-emoji", metavar="EMOJI", help="reaction to leave on synced messages (default 🦄)",
    )
    common.add_argument(
        "--react-edit-emoji", metavar="EMOJI",
        help="reaction when re-syncing an edited message (default 👾)",
    )
    common.add_argument(
        "--folder-format", metavar="TPL",
        help=f"folder template, may nest with `/` (default {DEFAULT_FOLDER!r})",
    )
    common.add_argument(
        "--filename-format", metavar="TPL",
        help=f"note filename template (default {DEFAULT_FILENAME!r})",
    )
    common.add_argument(
        "--dayfile-format", metavar="TPL",
        help=f"filename template for --layout per-day (default {DEFAULT_DAYFILE!r})",
    )

    parser = argparse.ArgumentParser(
        prog="telesync",
        description="Sync Telegram channel messages into a folder of Markdown files.",
        epilog=(
            "name template placeholders:\n  "
            + ", ".join(p for p in PLACEHOLDERS if p != "dt")
            + "\n  {dt} is the message datetime, so strftime specs work: {dt:%Y/%m}\n\n"
            "examples:\n"
            "  --folder-format '{channel}/{year}/{month}'\n"
            "  --filename-format '{id} - {title}'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", parents=[common], help="authorise this device (one time)")
    sub.add_parser("list", parents=[common], help="list channels/groups you can sync")

    # Common flags live on the leaf parsers only: argparse lets a subparser's
    # defaults clobber values already parsed by its parent.
    p_ch = sub.add_parser("channels", help="manage the saved channel list")
    ch_sub = p_ch.add_subparsers(dest="channels_command", required=True)
    p_add = ch_sub.add_parser("add", parents=[common], help="add channels to the saved list")
    p_add.add_argument("refs", nargs="+", metavar="REF")
    p_add.add_argument("--no-verify", action="store_true", help="skip the access check")
    p_rm = ch_sub.add_parser("rm", parents=[common], help="remove channels from the saved list")
    p_rm.add_argument("refs", nargs="+", metavar="REF")
    ch_sub.add_parser("ls", parents=[common], help="show the saved list")

    p_sync = sub.add_parser("sync", parents=[common], help="sync new messages once")
    p_sync.add_argument("--full", action="store_true", help="re-sync from the beginning")
    p_sync.add_argument("--limit", type=int, metavar="N", help="only the newest N messages")

    p_watch = sub.add_parser(
        "watch", parents=[common], help="sync, then stay connected for live updates"
    )
    p_watch.add_argument("--limit", type=int, metavar="N", help="backfill only N messages")
    p_watch.add_argument("--no-backfill", action="store_true", help="skip the initial sync")

    return parser


def make_client(cfg: Config):
    """A Telethon client, or the HTTP Bot API shim when only a token is set."""
    if cfg.mode == "bot-api":
        return BotAPI(cfg.bot_token)
    cfg.session.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(cfg.session), cfg.api_id, cfg.api_hash)


async def ensure_authorised(cfg: Config, client) -> bool:
    """Connect; with a bot token this also logs in non-interactively."""
    if cfg.mode == "bot-api":
        return True  # the token is the whole credential; nothing to connect
    await client.connect()
    if await client.is_user_authorized():
        return True
    if cfg.bot_token:
        await client.start(bot_token=cfg.bot_token)
        return True
    await client.disconnect()
    print("Not logged in. Run: telesync login", file=sys.stderr)
    return False


def resolve_channel_refs(cfg: Config, state: State) -> list[str]:
    """`-c` wins outright; otherwise saved list + TELEGRAM_CHANNELS, deduped."""
    if cfg.channels_from_cli:
        return cfg.channels
    return list(dict.fromkeys(state.subscriptions() + cfg.channels))


async def disconnect(cfg: Config, client) -> None:
    if cfg.mode != "bot-api":
        await client.disconnect()


async def cmd_login(cfg: Config) -> int:
    client = make_client(cfg)
    if cfg.mode == "bot-api":
        try:
            me = await client.get_me()
        except BotAPIError as exc:
            print(f"Bot API error: {exc}", file=sys.stderr)
            return 1
        print(f"Bot @{me.username} ({me.first_name}) — token works.")
        print("Mode: HTTP Bot API (no api_id/api_hash set).")
        print("Limits: no history backfill, and the bot must be an admin of the channel.")
        print("Set TELEGRAM_API_ID/TELEGRAM_API_HASH to enable backfill over MTProto.")
        return 0
    if cfg.bot_token:
        await client.start(bot_token=cfg.bot_token)
        me = await client.get_me()
        print(f"Logged in as bot @{me.username}. Session saved to {cfg.session}")
        print("Note: a bot only sees channels where it is an admin.")
    else:
        await client.start()
        me = await client.get_me()
        name = " ".join(filter(None, [me.first_name, me.last_name])) or me.username
        print(f"Logged in as {name}. Session saved to {cfg.session}")
    await client.disconnect()
    return 0


async def cmd_channels(cfg: Config, args) -> int:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    state = State.load(cfg.out_dir)

    if args.channels_command == "ls":
        saved = state.subscriptions()
        if not saved:
            print("No saved channels. Add one: telesync channels add @name")
        for ref in saved:
            meta = next(
                (c for c in state.data["channels"].values() if c.get("ref") == ref), {}
            )
            title = meta.get("title", "")
            print(f"{ref:<28}  {title}")
        for ref in cfg.channels:
            if ref not in saved:
                print(f"{ref:<28}  (from TELEGRAM_CHANNELS)")
        return 0

    if args.channels_command == "rm":
        for ref in args.refs:
            print(("removed " if state.unsubscribe(ref) else "not in list: ") + ref)
        state.save()
        return 0

    # add — verify access first so typos fail loudly rather than at sync time
    client = None
    if not args.no_verify:
        client = make_client(cfg)
        if not await ensure_authorised(cfg, client):
            return 1

    failures = 0
    for ref in args.refs:
        title, saved_ref = "", ref
        if client:
            try:
                chat = await resolve_channel(client, ref)
            except Exception as exc:
                failures += 1
                print(f"  ! {ref}: {exc}", file=sys.stderr)
                if cfg.is_bot:
                    print("    bots cannot resolve names or @usernames — use the numeric"
                          " channel id, or pass --no-verify", file=sys.stderr)
                continue
            title = getattr(chat, "title", "") or ref
            # store the canonical ref so later syncs don't re-scan the dialog list
            saved_ref = f"@{chat.username}" if getattr(chat, "username", None) else str(chat.id)
            entry = state.channel(channel_key(chat))
            entry["ref"] = saved_ref
            entry["title"] = title
        print(("added " if state.subscribe(saved_ref) else "already saved: ")
              + f"{saved_ref}  {title}")
    state.save()
    if client:
        await disconnect(cfg, client)
    print(f"Saved list: {state.path}")
    return 1 if failures else 0


async def list_via_updates(cfg: Config) -> int:
    """Bots can't enumerate chats, so show whichever ones appear in the queue."""
    api = BotAPI(cfg.bot_token)
    try:
        updates = await api.get_updates(None, 0)
    except BotAPIError as exc:
        print(f"Bot API error: {exc}", file=sys.stderr)
        return 1

    seen: dict[int, object] = {}
    for update in updates:
        for value in update.values():
            if isinstance(value, dict) and "chat" in value:
                chat = adapt_chat(value["chat"])
                seen[chat.id] = chat
    if not seen:
        print("No chats in the pending update queue.\n"
              "Add the bot as an admin to a channel, post a message there, then retry.\n"
              "You can also add it directly: telesync channels add @channelname")
        return 0
    for chat in seen.values():
        handle = f"@{chat.username}" if chat.username else str(chat.bot_api_id)
        print(f"{'channel' if chat.broadcast else 'chat':8}  {handle:<28}  {chat.title}")
    return 0


async def cmd_list(cfg: Config) -> int:
    if cfg.mode == "bot-api":
        return await list_via_updates(cfg)
    if cfg.is_bot:
        print("Bots cannot enumerate chats. Add channels explicitly:\n"
              "  telesync channels add -1001234567890", file=sys.stderr)
        return 2
    client = make_client(cfg)
    if not await ensure_authorised(cfg, client):
        return 1
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, types.Channel):
            continue
        kind = "channel" if entity.broadcast else "group"
        handle = f"@{entity.username}" if entity.username else str(entity.id)
        print(f"{kind:8}  {handle:<28}  {dialog.name}")
    await disconnect(cfg, client)
    return 0


def require_refs(cfg: Config, state: State) -> list[str] | None:
    refs = resolve_channel_refs(cfg, state)
    if refs:
        return refs
    print("No channels configured. Add one with `telesync channels add @name`,"
          " pass -c @name, or set TELEGRAM_CHANNELS.", file=sys.stderr)
    return None


async def cmd_sync(cfg: Config, *, full: bool, limit: int | None) -> int:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    state = State.load(cfg.out_dir)
    refs = require_refs(cfg, state)
    if refs is None:
        return 2

    if cfg.mode == "bot-api":
        if full:
            print("--full is not available over the Bot API: Telegram exposes no history"
                  " to bots, only the pending update queue.", file=sys.stderr)
        return await run_updates(cfg, state, refs, once=True)

    client = make_client(cfg)
    if not await ensure_authorised(cfg, client):
        return 1
    reactor = Reactor(client, cfg)
    failures = 0
    for ref in refs:
        try:
            await sync_channel(client, cfg, state, ref, limit=limit, full=full, reactor=reactor)
        except Exception as exc:
            failures += 1
            print(f"  ! {ref}: {exc}", file=sys.stderr)
    if reactor.count:
        print(f"{reactor.emoji} reacted to {reactor.count} message(s)")
    await disconnect(cfg, client)
    print(f"Output: {cfg.out_dir}")
    return 1 if failures else 0


async def cmd_watch(cfg: Config, *, limit: int | None, backfill: bool) -> int:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    state = State.load(cfg.out_dir)
    refs = require_refs(cfg, state)
    if refs is None:
        return 2

    if cfg.mode == "bot-api":
        return await run_updates(cfg, state, refs, once=False)

    client = make_client(cfg)
    if not await ensure_authorised(cfg, client):
        return 1
    reactor = Reactor(client, cfg)

    chats = []
    for ref in refs:
        try:
            chats.append(await resolve_channel(client, ref))
        except Exception as exc:
            print(f"  ! cannot resolve {ref}: {exc}", file=sys.stderr)
    if not chats:
        await disconnect(cfg, client)
        return 1

    if backfill:
        for ref in refs:
            try:
                await sync_channel(client, cfg, state, ref, limit=limit, reactor=reactor)
            except Exception as exc:
                print(f"  ! {ref}: {exc}", file=sys.stderr)

    me = await client.get_me()
    peer_map = {utils.get_peer_id(c): c for c in chats}
    written_at: dict[tuple[int, int], float] = {}

    async def handle(event) -> None:
        chat = await event.get_chat()
        path = await write_message(client, event.message, chat, cfg, reactor)
        if path:
            print(f"  + {path.relative_to(cfg.out_dir)}")
        written_at[(utils.get_peer_id(chat), event.message.id)] = time.monotonic()
        state.record(channel_key(chat), last_id=event.message.id)
        state.save()

    async def handle_reaction(update) -> None:
        """A reaction on any watched message (re)writes its note — react to a
        message in Telegram to pull it into the archive, however old it is."""
        target = reaction_target(update, self_id=me.id)
        if target is None:
            return
        peer_id, msg_id = target
        chat = peer_map.get(peer_id)
        if chat is None:
            return
        if time.monotonic() - written_at.get((peer_id, msg_id), -REACTION_COOLDOWN) < REACTION_COOLDOWN:
            return
        message = await client.get_messages(chat, ids=msg_id)
        if message is None:
            return
        written_at[(peer_id, msg_id)] = time.monotonic()
        path = await write_message(client, message, chat, cfg, reactor)
        if path:
            print(f"  ★ {path.relative_to(cfg.out_dir)}  (reaction)")

    client.add_event_handler(handle, events.NewMessage(chats=chats))
    client.add_event_handler(handle, events.MessageEdited(chats=chats))
    client.add_event_handler(
        handle_reaction,
        events.Raw(types=(types.UpdateBotMessageReaction, types.UpdateMessageReactions)),
    )

    print(f"Watching {len(chats)} chat(s) → {cfg.out_dir}   (Ctrl-C to stop)")
    try:
        await client.run_until_disconnected()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await disconnect(cfg, client)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.command == "login":
        coro = cmd_login(cfg)
    elif args.command == "list":
        coro = cmd_list(cfg)
    elif args.command == "channels":
        coro = cmd_channels(cfg, args)
    elif args.command == "sync":
        coro = cmd_sync(cfg, full=args.full, limit=args.limit)
    else:
        coro = cmd_watch(cfg, limit=args.limit, backfill=not args.no_backfill)

    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
