"""HTTP Bot API transport.

A bot token on its own cannot speak MTProto (that needs api_id/api_hash), so
this module talks to https://api.telegram.org instead and adapts the JSON it
returns into objects shaped like Telethon's, letting `render.py` and the
writers in `sync.py` stay transport-agnostic.

Hard limits of this transport, imposed by Telegram:
  * no history — only messages that arrive while the bot is an admin
  * getUpdates is exclusive: one poller at a time, and no webhook set
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from telethon.tl import types

API_ROOT = "https://api.telegram.org"

# Bot API entity names -> the Telethon classes render.py understands
ENTITY_MAP = {
    "bold": types.MessageEntityBold,
    "italic": types.MessageEntityItalic,
    "underline": types.MessageEntityUnderline,
    "strikethrough": types.MessageEntityStrike,
    "spoiler": types.MessageEntitySpoiler,
    "code": types.MessageEntityCode,
    "blockquote": types.MessageEntityBlockquote,
    "expandable_blockquote": types.MessageEntityBlockquote,
}

UPDATE_KINDS = ("channel_post", "edited_channel_post", "message", "edited_message")


class BotAPIError(Exception):
    pass


class BotAPI:
    """Minimal async wrapper over the HTTP Bot API (stdlib only)."""

    def __init__(self, token: str, timeout: int = 60):
        self.token = token
        self.timeout = timeout

    # --- transport ---------------------------------------------------------

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        payload = json.dumps(params).encode()
        req = urllib.request.Request(
            f"{API_ROOT}/bot{self.token}/{method}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout + 10) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except Exception:
                raise BotAPIError(f"{method}: HTTP {exc.code}") from exc
            raise BotAPIError(
                f"{method}: {body.get('description', exc.code)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BotAPIError(f"{method}: {exc.reason}") from exc
        except OSError as exc:
            # e.g. a socket read timing out mid-response; the polling loop
            # retries on BotAPIError, so a network hiccup must not escape raw
            raise BotAPIError(f"{method}: {exc}") from exc
        if not body.get("ok"):
            raise BotAPIError(f"{method}: {body.get('description')}")
        return body["result"]

    async def call(self, method: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        return await asyncio.to_thread(self._request, method, params)

    # --- duck-typing so sync.write_message can treat this like a client ----

    async def is_bot(self) -> bool:
        return True

    async def get_me(self):
        return SimpleNamespace(**await self.call("getMe"))

    async def get_entity(self, ref):
        """Resolve @username / numeric id via getChat."""
        return adapt_chat(await self.call("getChat", chat_id=ref))

    async def set_reaction(self, chat, message_id: int, emoji: str) -> None:
        await self.call(
            "setMessageReaction",
            chat_id=chat_id_of(chat),
            message_id=message_id,
            reaction=[{"type": "emoji", "emoji": emoji}],
        )

    async def get_updates(self, offset: int | None, timeout: int) -> list[dict]:
        return await self.call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            # message_reaction must be requested explicitly; the Bot API never
            # delivers it by default.
            allowed_updates=list(UPDATE_KINDS) + ["message_reaction"],
        )

    async def download_media(self, message, file: str) -> str | None:
        """Mirrors TelegramClient.download_media(message, file=<dir>)."""
        file_id = getattr(message, "_file_id", None)
        if not file_id:
            return None
        info = await self.call("getFile", file_id=file_id)
        remote = info.get("file_path")
        if not remote:
            return None
        name = getattr(message, "_file_name", None) or Path(remote).name
        target = Path(file) / name
        url = f"{API_ROOT}/file/bot{self.token}/{remote}"
        await asyncio.to_thread(_download_to, url, target)
        return str(target)


def _download_to(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=300) as resp:
        target.write_bytes(resp.read())


def chat_id_of(chat) -> int | str:
    """The id the Bot API expects (`-100…` form), whatever we were handed."""
    if isinstance(chat, (int, str)):
        return chat
    return getattr(chat, "bot_api_id", None) or chat.id


# --- adapters --------------------------------------------------------------


def adapt_chat(d: dict) -> SimpleNamespace:
    """Bot API chat -> Telethon-ish entity.

    Bot API ids for channels carry a `-100` prefix; MTProto uses the bare id.
    Normalise to the bare id so both transports key state identically, keeping
    the prefixed form for API calls.
    """
    raw = int(d["id"])
    bare = raw
    text = str(raw)
    if text.startswith("-100"):
        bare = int(text[4:])
    elif raw < 0:
        bare = -raw
    return SimpleNamespace(
        id=bare,
        bot_api_id=raw,
        title=d.get("title") or d.get("username") or str(raw),
        username=d.get("username"),
        broadcast=d.get("type") == "channel",
    )


def _adapt_entities(raw: list[dict] | None) -> list:
    out = []
    for ent in raw or []:
        kind = ent.get("type")
        offset, length = ent.get("offset", 0), ent.get("length", 0)
        if kind == "pre":
            out.append(
                types.MessageEntityPre(
                    offset=offset, length=length, language=ent.get("language") or ""
                )
            )
        elif kind == "text_link":
            out.append(
                types.MessageEntityTextUrl(
                    offset=offset, length=length, url=ent.get("url", "")
                )
            )
        elif kind == "text_mention" and ent.get("user"):
            out.append(
                types.MessageEntityMentionName(
                    offset=offset, length=length, user_id=ent["user"]["id"]
                )
            )
        elif kind in ENTITY_MAP:
            out.append(ENTITY_MAP[kind](offset=offset, length=length))
    return out


def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def _largest_photo(photos: list[dict]) -> dict:
    return max(photos, key=lambda p: p.get("file_size") or p.get("width", 0))


def _adapt_poll(poll: dict) -> SimpleNamespace:
    return SimpleNamespace(
        poll=SimpleNamespace(
            question=SimpleNamespace(text=poll.get("question", "")),
            answers=[
                SimpleNamespace(text=SimpleNamespace(text=o.get("text", "")))
                for o in poll.get("options", [])
            ],
        )
    )


def adapt_message(d: dict) -> SimpleNamespace:
    """Bot API message -> object with the attributes render.py reads."""
    text = d.get("text") or d.get("caption") or ""
    entities = _adapt_entities(d.get("entities") or d.get("caption_entities"))

    msg = SimpleNamespace(
        id=d["message_id"],
        message=text,
        entities=entities,
        date=_ts(d.get("date")),
        edit_date=_ts(d.get("edit_date")),
        views=None,
        forwards=None,
        post_author=d.get("author_signature"),
        grouped_id=d.get("media_group_id"),
        reply_to=None,
        photo=None, video=None, voice=None, video_note=None, audio=None,
        sticker=None, gif=None, document=None, web_preview=None, poll=None,
        geo=None, contact=None, media=None,
        _file_id=None, _file_name=None,
    )

    if reply := d.get("reply_to_message"):
        msg.reply_to = SimpleNamespace(reply_to_msg_id=reply.get("message_id"))

    if photos := d.get("photo"):
        best = _largest_photo(photos)
        msg.photo = True
        msg._file_id = best.get("file_id")
        msg._file_name = f"photo_{d['message_id']}.jpg"
    for key, attr in (
        ("video", "video"), ("voice", "voice"), ("video_note", "video_note"),
        ("audio", "audio"), ("sticker", "sticker"), ("animation", "gif"),
        ("document", "document"),
    ):
        if blob := d.get(key):
            setattr(msg, attr, True)
            msg._file_id = msg._file_id or blob.get("file_id")
            msg._file_name = msg._file_name or blob.get("file_name")

    if poll := d.get("poll"):
        msg.poll = _adapt_poll(poll)
    if loc := (d.get("location") or (d.get("venue") or {}).get("location")):
        msg.geo = SimpleNamespace(lat=loc.get("latitude"), long=loc.get("longitude"))
    if contact := d.get("contact"):
        msg.contact = SimpleNamespace(
            first_name=contact.get("first_name", ""),
            last_name=contact.get("last_name"),
            phone_number=contact.get("phone_number", ""),
        )

    msg.media = bool(msg._file_id or msg.poll or msg.geo or msg.contact)

    async def get_sender():
        sender = d.get("from") or d.get("sender_chat")
        if not sender:
            return None
        if "title" in sender:
            return SimpleNamespace(title=sender["title"])
        return types.User(
            id=sender.get("id", 0),
            first_name=sender.get("first_name"),
            last_name=sender.get("last_name"),
            username=sender.get("username"),
        )

    msg.get_sender = get_sender
    return msg
