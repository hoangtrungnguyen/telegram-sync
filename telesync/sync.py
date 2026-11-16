"""Core sync logic: pull messages from Telegram, write Markdown files."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telethon import TelegramClient, utils
from telethon.tl import types

from .config import Config
from .render import (
    DEFAULT_DAYFILE,
    DEFAULT_FILENAME,
    build_context,
    channel_folder,
    day_filename,
    dump_frontmatter,
    message_filename,
    render_day_block,
    render_document,
    slugify,
)
from .state import State

BLOCK_RE = re.compile(r"<!-- telesync:(\d+) -->\n(.*?)(?=\n<!-- telesync:\d+ -->|\Z)", re.S)
# Errors that mean "network is flaky", not "Telegram refused the reaction".
_TRANSIENT = re.compile(r"timed out|timeout|connection reset|nodename nor servname|temporarily", re.I)


class Reactor:
    """Marks synced messages in Telegram with an emoji reaction (🦄 by default).

    Reactions are best-effort: channels can restrict which emoji are allowed and
    reacting is rate limited, so the first failure switches it off for the run
    rather than aborting the sync.
    """

    def __init__(self, client, cfg: Config):
        self.client = client
        self.emoji = cfg.react_emoji
        self.edit_emoji = cfg.react_edit_emoji
        self.enabled = cfg.react
        self.count = 0

    async def react(self, chat, message_id: int, *, edited: bool = False) -> bool:
        if not self.enabled:
            return False
        emoji = self.edit_emoji if edited else self.emoji
        try:
            # the Bot API transport exposes its own reaction call
            if hasattr(self.client, "set_reaction"):
                await self.client.set_reaction(chat, message_id, emoji)
            else:
                from telethon.tl.functions.messages import SendReactionRequest

                await self.client(
                    SendReactionRequest(
                        peer=chat,
                        msg_id=message_id,
                        reaction=[types.ReactionEmoji(emoticon=emoji)],
                    )
                )
        except Exception as exc:
            # A network hiccup is not a reason to stop reacting for the rest
            # of a watch that may run for days; only give up on real refusals.
            if _TRANSIENT.search(str(exc)) or isinstance(exc, (TimeoutError, ConnectionError)):
                print(f"  ! reaction on {message_id} skipped ({type(exc).__name__}: {exc})")
                return False
            self.enabled = False
            print(f"  ! reactions disabled for this run ({type(exc).__name__}: {exc})")
            return False
        self.count += 1
        return True


def reaction_target(update, self_id: int | None = None) -> tuple[int, int] | None:
    """(marked peer id, message id) if this raw update is a reaction worth
    syncing, else None.

    Skips reaction removals, and — for bot sessions, where Telegram names the
    actor — the client's own reactions: the 🦄 the Reactor leaves would
    otherwise re-trigger the very write it marks.
    """
    if isinstance(update, types.UpdateBotMessageReaction):
        if self_id is not None and getattr(update.actor, "user_id", None) == self_id:
            return None
        if not update.new_reactions:
            return None
        return utils.get_peer_id(update.peer), update.msg_id
    if isinstance(update, types.UpdateMessageReactions):
        if not (getattr(update.reactions, "results", None) or []):
            return None
        return utils.get_peer_id(update.peer), update.msg_id
    return None


def channel_key(chat) -> str:
    """Stable identity for a chat across renames."""
    return str(chat.id)


def channel_folder_name(chat) -> str:
    base = slugify(getattr(chat, "title", "") or getattr(chat, "username", "") or "")
    return base or f"channel-{chat.id}"


class ChannelNotFound(Exception):
    pass


async def find_by_title(client: TelegramClient, name: str):
    """Look a chat up by its display name, as shown in the Telegram app."""
    if await client.is_bot():
        raise ChannelNotFound(
            f"cannot look up {name!r} by name: bots can only use numeric channel ids"
        )
    want = name.strip().casefold()
    exact, partial = [], []
    async for dialog in client.iter_dialogs():
        title = (dialog.name or "").strip()
        if not title:
            continue
        folded = title.casefold()
        if folded == want:
            exact.append(dialog.entity)
        elif want in folded:
            partial.append(dialog.entity)

    matches = exact or partial
    if not matches:
        raise ChannelNotFound(
            f"no chat named {name!r} — check `telesync list` for the exact name"
        )
    if len(matches) > 1:
        names = ", ".join(f"{getattr(m, 'title', '?')} ({m.id})" for m in matches[:5])
        raise ChannelNotFound(f"{name!r} is ambiguous: {names}. Use the id or @username.")
    return matches[0]


async def resolve_channel(client: TelegramClient, ref: str):
    """Accept @username, t.me links, numeric ids, or the channel's display name."""
    ref = ref.strip()
    m = re.match(r"^(?:https?://)?t\.me/(?:s/)?([A-Za-z0-9_]+)/?$", ref)
    if m:
        ref = m.group(1)
    if re.fullmatch(r"-?\d+", ref):
        return await client.get_entity(int(ref))

    handle = ref.lstrip("@")
    # A bare word could be either a username or a title; usernames are cheap to
    # try first, and titles (with spaces) can only be resolved via the dialogs.
    if re.fullmatch(r"[A-Za-z0-9_]{4,32}", handle):
        try:
            return await client.get_entity(handle)
        except Exception:
            pass
    return await find_by_title(client, ref)


async def author_of(client: TelegramClient, message, chat) -> str | None:
    if getattr(message, "post_author", None):
        return message.post_author
    if isinstance(chat, types.Channel) and chat.broadcast:
        return getattr(chat, "title", None)
    try:
        sender = await message.get_sender()
    except Exception:
        return None
    if sender is None:
        return None
    if isinstance(sender, types.User):
        name = " ".join(filter(None, [sender.first_name, sender.last_name]))
        return name or (f"@{sender.username}" if sender.username else None)
    return getattr(sender, "title", None)


async def download_media(client: TelegramClient, message, cfg: Config, ch_dir: Path) -> list[str]:
    """Download the message attachment; return paths relative to the note."""
    if not cfg.download_media or not message.media:
        return []
    if isinstance(message.media, types.MessageMediaWebPage):
        return []

    media_dir = ch_dir / cfg.media_dir
    media_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(media_dir.glob(f"{message.id}-*"))
    if existing:
        return [f"{cfg.media_dir}/{p.name}" for p in existing]

    try:
        downloaded = await client.download_media(message, file=str(media_dir))
    except Exception as exc:  # network hiccups shouldn't abort the whole sync
        print(f"  ! media download failed for message {message.id}: {exc}")
        return []
    if not downloaded:
        return []

    src = Path(downloaded)
    target = src.with_name(f"{message.id}-{src.name}")
    src.replace(target)
    return [f"{cfg.media_dir}/{target.name}"]


def write_per_message(
    message, chat, author, media_files, ch_dir: Path, template: str = DEFAULT_FILENAME
) -> Path:
    ch_dir.mkdir(parents=True, exist_ok=True)
    path = ch_dir / message_filename(message, chat, author, template)
    path.parent.mkdir(parents=True, exist_ok=True)
    # An edited message keeps its id but may change its title: drop the stale file
    # so the edit replaces the note instead of sitting next to it.
    for stale in _stale_notes(ch_dir, message.id, template, path):
        stale.unlink()
    path.write_text(render_document(message, chat, author, media_files), encoding="utf-8")
    return path


_FM_ID = re.compile(r"^id: (\d+)$", re.M)


def _stale_notes(ch_dir: Path, message_id: int, template: str, keep: Path) -> list[Path]:
    """Earlier notes for this message id in the same folder.

    With {id} in the template the name is enough; otherwise fall back to the
    `id:` frontmatter key of each note in the folder (small, so cheap).
    """
    id_token = re.compile(rf"(?<!\d){message_id}(?!\d)")
    found = []
    for p in ch_dir.glob("*.md"):
        if p == keep or not p.is_file():
            continue
        if "{id}" in template:
            if id_token.search(p.name):
                found.append(p)
            continue
        head = p.read_text(encoding="utf-8")[:600]
        if head.startswith("---") and (m := _FM_ID.search(head)) and int(m.group(1)) == message_id:
            found.append(p)
    return found


def write_per_day(
    message, chat, author, media_files, ch_dir: Path, template: str = DEFAULT_DAYFILE
) -> Path:
    """Insert/replace this message's block inside its day file, keeping id order."""
    ch_dir.mkdir(parents=True, exist_ok=True)
    path = ch_dir / day_filename(message, chat, author, template)
    path.parent.mkdir(parents=True, exist_ok=True)

    blocks: dict[int, str] = {}
    if path.exists():
        for match in BLOCK_RE.finditer(path.read_text(encoding="utf-8")):
            blocks[int(match.group(1))] = match.group(2).rstrip() + "\n"

    block = render_day_block(message, chat, author, media_files)
    blocks[message.id] = block.split("\n", 1)[1]  # drop the marker; re-added below

    ctx = build_context(message, chat, author)
    header = dump_frontmatter(
        {
            "date": ctx["date"],
            "channel": ctx["channel_title"],
            "channel_id": chat.id,
            "source": "telegram",
        }
    )
    parts = [header, f"\n# {ctx['date']}\n"]
    for mid in sorted(blocks):
        parts.append(f"\n<!-- telesync:{mid} -->\n{blocks[mid].rstrip()}\n")
    path.write_text("".join(parts), encoding="utf-8")
    return path


async def write_message(
    client: TelegramClient, message, chat, cfg: Config, reactor: "Reactor | None" = None
) -> Path | None:
    """Render one message to disk. Returns the file path, or None if skipped."""
    if isinstance(message, types.MessageService):
        return None
    if not (message.message or message.media):
        return None

    author = await author_of(client, message, chat)
    ch_dir = cfg.channel_dir(channel_folder(message, chat, author, cfg.folder_template))
    media_files = await download_media(client, message, cfg, ch_dir)

    if cfg.layout == "per-day":
        path = write_per_day(
            message, chat, author, media_files, ch_dir, cfg.dayfile_template
        )
    else:
        path = write_per_message(
            message, chat, author, media_files, ch_dir, cfg.filename_template
        )

    if reactor is not None:
        await reactor.react(
            chat, message.id, edited=bool(getattr(message, "edit_date", None))
        )
    return path


async def _iter_user_messages(client: TelegramClient, chat, min_id: int, limit: int | None):
    """History walk — only available to user sessions."""
    kwargs: dict[str, Any] = {"reverse": True}
    if min_id:
        kwargs["min_id"] = min_id
    if limit:
        # `reverse` + `limit` walks forward from the oldest; for a capped run the
        # newest messages are the interesting ones, so walk backwards instead.
        kwargs["reverse"] = False
        kwargs["limit"] = limit
    async for message in client.iter_messages(chat, **kwargs):
        yield message


async def _iter_bot_messages(
    client: TelegramClient, chat, min_id: int, limit: int | None,
    batch: int = 100, max_gap: int = 300,
):
    """Bots may not call getHistory, but may fetch messages by explicit id.

    So walk forward in id batches from the sync point and stop once `max_gap`
    consecutive ids come back empty (deleted/service messages leave holes).
    """
    next_id = min_id + 1
    gap = 0
    produced = 0
    while gap < max_gap:
        ids = list(range(next_id, next_id + batch))
        messages = await client.get_messages(chat, ids=ids)
        found = [m for m in messages if m is not None]
        gap = 0 if found else gap + batch
        for message in found:
            yield message
            produced += 1
            if limit and produced >= limit:
                return
        next_id += batch


async def sync_channel(
    client: TelegramClient,
    cfg: Config,
    state: State,
    ref: str,
    *,
    limit: int | None = None,
    full: bool = False,
    reactor: "Reactor | None" = None,
) -> int:
    chat = await resolve_channel(client, ref)
    key = channel_key(chat)
    title = getattr(chat, "title", ref)
    last_id = 0 if full else state.last_id(key)

    recheck_from = max(0, last_id - cfg.recheck) if cfg.recheck else last_id
    mode = "bot" if await client.is_bot() else "user"
    print(f"→ {title} (id {chat.id}) — from message id {recheck_from} [{mode}]")

    written = 0
    highest = last_id
    iterator = (
        _iter_bot_messages(client, chat, recheck_from, limit)
        if mode == "bot"
        else _iter_user_messages(client, chat, recheck_from, limit)
    )

    async for message in iterator:
        path = await write_message(client, message, chat, cfg, reactor)
        highest = max(highest, message.id)
        if path:
            written += 1
            if written % 25 == 0:
                print(f"  … {written} messages")

    state.record(
        key,
        last_id=highest,
        title=str(title),
        folder=channel_folder_name(chat),
        last_sync=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    state.save()
    print(f"  ✓ {written} file(s) written, last id {highest}")
    return written
