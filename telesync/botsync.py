"""Update-polling loop for the HTTP Bot API transport."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from .botapi import UPDATE_KINDS, BotAPI, BotAPIError, adapt_chat, adapt_message
from .config import Config
from .state import State
from .sync import Reactor, channel_key, write_message

OFFSET_KEY = "bot_api_offset"


def _normalise(ref: str) -> str:
    ref = ref.strip().lstrip("@").casefold()
    ref = re.sub(r"^(?:https?://)?t\.me/(?:s/)?", "", ref)
    if re.fullmatch(r"-?\d+", ref):
        return ref.lstrip("-").removeprefix("100")
    return ref.rstrip("/")


def chat_matches(chat, refs: list[str]) -> bool:
    """Does this update's chat correspond to one of the configured refs?"""
    wanted = {_normalise(r) for r in refs}
    candidates = {str(chat.id)}
    if getattr(chat, "bot_api_id", None):
        candidates.add(_normalise(str(chat.bot_api_id)))
    if chat.username:
        candidates.add(chat.username.casefold())
    if chat.title:
        candidates.add(chat.title.casefold())
    return bool(candidates & wanted)


async def _handle(api: BotAPI, cfg: Config, state: State, reactor: Reactor,
                  raw_chat: dict, raw_msg: dict) -> bool:
    chat = adapt_chat(raw_chat)
    message = adapt_message(raw_msg)
    path = await write_message(api, message, chat, cfg, reactor)
    if not path:
        return False
    print(f"  + {path.relative_to(cfg.out_dir)}")
    state.record(
        channel_key(chat),
        last_id=message.id,
        title=chat.title,
        last_sync=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return True


async def run_updates(
    cfg: Config, state: State, refs: list[str], *, once: bool, poll_timeout: int = 25
) -> int:
    """Consume pending updates (`once`) or keep long-polling until interrupted.

    The Bot API only offers an update queue — messages posted before the bot
    joined, or older than ~24h, are simply not retrievable here.
    """
    api = BotAPI(cfg.bot_token, timeout=poll_timeout)
    reactor = Reactor(api, cfg)

    try:
        me = await api.get_me()
    except BotAPIError as exc:
        print(f"Bot API error: {exc}")
        return 1
    print(f"Bot @{me.username} — watching {len(refs)} chat(s) → {cfg.out_dir}")
    if not once:
        print("(Ctrl-C to stop)")

    offset = state.data.get(OFFSET_KEY)
    written = 0
    skipped = set()

    while True:
        try:
            updates = await api.get_updates(offset, 0 if once else poll_timeout)
        except BotAPIError as exc:
            print(f"  ! {exc}")
            if once:
                return 1
            await asyncio.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            if reaction := update.get("message_reaction"):
                # The Bot API tells us a message was reacted to but offers no
                # way to fetch its content, so we can only point at MTProto.
                chat = adapt_chat(reaction["chat"])
                actor_id = (reaction.get("user") or {}).get("id")
                if (chat_matches(chat, refs) and actor_id != me.id
                        and reaction.get("new_reaction")):
                    print(f"  ! reaction on message {reaction['message_id']} in"
                          f" {chat.title} — the Bot API cannot fetch message content;"
                          " set TELEGRAM_API_ID/TELEGRAM_API_HASH and run"
                          " `telesync watch` to sync reacted messages")
                continue
            for kind in UPDATE_KINDS:
                raw_msg = update.get(kind)
                if not raw_msg:
                    continue
                chat = adapt_chat(raw_msg["chat"])
                if not chat_matches(chat, refs):
                    if chat.title not in skipped:
                        skipped.add(chat.title)
                        print(f"  · ignoring messages from {chat.title} (not configured)")
                    continue
                if await _handle(api, cfg, state, reactor, raw_msg["chat"], raw_msg):
                    written += 1

        state.data[OFFSET_KEY] = offset
        state.save()

        if once:
            if not updates:
                break

    if reactor.count:
        print(f"  {reactor.emoji} reacted to {reactor.count} message(s)")
    print(f"✓ {written} file(s) written")
    return 0
