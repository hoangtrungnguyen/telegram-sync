"""Convert Telegram messages into Markdown documents."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable

import yaml
from telethon.tl import types

# Sentinels used for block-level constructs that cannot be expressed by simply
# wrapping a span (they need per-line prefixes or their own lines).
BQ_OPEN = "\x00bq\x01"
BQ_CLOSE = "\x00/bq\x01"


def _wrappers(entity) -> tuple[str, str] | None:
    """Return the (prefix, suffix) markers for an inline entity, or None to skip."""
    if isinstance(entity, types.MessageEntityBold):
        return "**", "**"
    if isinstance(entity, types.MessageEntityItalic):
        return "*", "*"
    if isinstance(entity, types.MessageEntityUnderline):
        return "<u>", "</u>"
    if isinstance(entity, types.MessageEntityStrike):
        return "~~", "~~"
    if isinstance(entity, types.MessageEntitySpoiler):
        return "||", "||"
    if isinstance(entity, types.MessageEntityCode):
        return "`", "`"
    if isinstance(entity, types.MessageEntityPre):
        lang = getattr(entity, "language", "") or ""
        return f"\n```{lang}\n", "\n```\n"
    if isinstance(entity, types.MessageEntityTextUrl):
        return "[", f"]({entity.url})"
    if isinstance(entity, types.MessageEntityMentionName):
        return "[", f"](tg://user?id={entity.user_id})"
    if isinstance(entity, types.MessageEntityBlockquote):
        return BQ_OPEN, BQ_CLOSE
    return None


def entities_to_markdown(text: str, entities: Iterable | None) -> str:
    """Apply Telegram entities to plain text, producing CommonMark.

    Telegram entity offsets are in UTF-16 code units, so the text is sliced in
    that encoding before being decoded back.
    """
    if not text:
        return ""
    entities = list(entities or [])
    if not entities:
        return text

    buf = text.encode("utf-16-le")
    events: list[tuple[int, int, int, str]] = []
    for ent in entities:
        markers = _wrappers(ent)
        if not markers:
            continue
        prefix, suffix = markers
        start, end = ent.offset, ent.offset + ent.length
        # closing markers sort before opening ones at the same position;
        # inner spans close first, outer spans open first.
        events.append((start, 1, -ent.length, prefix))
        events.append((end, 0, ent.length, suffix))

    if not events:
        return text

    events.sort(key=lambda e: (e[0], e[1], e[2]))
    out: list[str] = []
    cursor = 0
    for pos, _kind, _order, marker in events:
        if pos > cursor:
            out.append(buf[cursor * 2 : pos * 2].decode("utf-16-le", errors="replace"))
            cursor = pos
        out.append(marker)
    out.append(buf[cursor * 2 :].decode("utf-16-le", errors="replace"))
    return _apply_blockquotes("".join(out))


def _apply_blockquotes(text: str) -> str:
    """Turn blockquote sentinels into `> ` line prefixes."""
    if BQ_OPEN not in text:
        return text

    def repl(match: re.Match) -> str:
        inner = match.group(1)
        return "\n".join(f"> {line}" for line in inner.split("\n"))

    text = re.sub(
        re.escape(BQ_OPEN) + r"(.*?)" + re.escape(BQ_CLOSE), repl, text, flags=re.S
    )
    return text.replace(BQ_OPEN, "").replace(BQ_CLOSE, "")


def slugify(text: str, max_len: int = 60) -> str:
    """Filesystem-safe, lowercase slug."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-")


def media_kind(message) -> str | None:
    """Short human label for the message's attachment, if any."""
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.voice:
        return "voice"
    if message.video_note:
        return "video_note"
    if message.audio:
        return "audio"
    if message.sticker:
        return "sticker"
    if message.gif:
        return "animation"
    if message.document:
        return "document"
    if message.web_preview:
        return "link_preview"
    if message.poll:
        return "poll"
    if message.geo:
        return "location"
    if message.contact:
        return "contact"
    return None


def message_link(chat, message_id: int) -> str | None:
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    chat_id = getattr(chat, "id", None)
    if chat_id:
        return f"https://t.me/c/{chat_id}/{message_id}"
    return None


def _local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def build_frontmatter(message, chat, author: str | None, media_files: list[str]) -> dict[str, Any]:
    date = _local(message.date)
    fm: dict[str, Any] = {
        "id": message.id,
        "channel": getattr(chat, "title", None) or getattr(chat, "username", None) or str(chat.id),
        "channel_id": chat.id,
        "date": date.isoformat() if date else None,
        "source": "telegram",
    }
    if getattr(chat, "username", None):
        fm["channel_username"] = f"@{chat.username}"
    if author:
        fm["author"] = author
    if message.edit_date:
        edited = _local(message.edit_date)
        fm["edited"] = edited.isoformat() if edited else None
    if message.views:
        fm["views"] = message.views
    if message.forwards:
        fm["forwards"] = message.forwards
    if message.reply_to and getattr(message.reply_to, "reply_to_msg_id", None):
        fm["reply_to"] = message.reply_to.reply_to_msg_id
    if getattr(message, "grouped_id", None):
        fm["album"] = message.grouped_id
    kind = media_kind(message)
    if kind:
        fm["media_type"] = kind
    if media_files:
        fm["media"] = media_files
    link = message_link(chat, message.id)
    if link:
        fm["url"] = link
    return {k: v for k, v in fm.items() if v is not None}


def dump_frontmatter(fm: dict[str, Any]) -> str:
    body = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=1000).rstrip()
    return f"---\n{body}\n---\n"


def _poll_markdown(message) -> str:
    poll = message.poll.poll
    lines = [f"**Poll:** {poll.question.text if hasattr(poll.question, 'text') else poll.question}"]
    for answer in poll.answers:
        text = answer.text.text if hasattr(answer.text, "text") else answer.text
        lines.append(f"- [ ] {text}")
    return "\n".join(lines)


def render_body(message, media_files: list[str]) -> str:
    """Markdown body for a single message (no frontmatter)."""
    parts: list[str] = []

    for rel in media_files:
        if re.search(r"\.(png|jpe?g|gif|webp|bmp|svg)$", rel, re.I):
            parts.append(f"![]({rel})")
        else:
            parts.append(f"[{rel.rsplit('/', 1)[-1]}]({rel})")

    text = entities_to_markdown(message.message or "", message.entities)
    if text.strip():
        parts.append(text.strip())

    if message.poll:
        parts.append(_poll_markdown(message))

    if message.geo:
        geo = message.geo
        lat, lon = getattr(geo, "lat", None), getattr(geo, "long", None)
        if lat is not None and lon is not None:
            parts.append(f"[Location {lat}, {lon}](https://maps.google.com/?q={lat},{lon})")

    if message.contact:
        c = message.contact
        parts.append(f"**Contact:** {c.first_name} {c.last_name or ''} — {c.phone_number}".strip())

    if not parts and (kind := media_kind(message)):
        parts.append(f"*({kind})*")

    return "\n\n".join(parts).strip()


def render_document(message, chat, author: str | None, media_files: list[str]) -> str:
    fm = build_frontmatter(message, chat, author, media_files)
    return dump_frontmatter(fm) + "\n" + render_body(message, media_files) + "\n"


# --- name templates --------------------------------------------------------

DEFAULT_FOLDER = "{channel}"
DEFAULT_FILENAME = "{date}-{time}-{id}-{slug}"
DEFAULT_DAYFILE = "{date}"

PLACEHOLDERS = (
    "date", "time", "datetime", "year", "month", "day", "hour", "minute",
    "dt", "id", "slug", "title", "channel", "channel_title", "channel_id",
    "username", "author", "media_type",
)

_ILLEGAL = re.compile(r'[<>:"\\|?*\x00-\x1f]')


class TemplateError(Exception):
    pass


def sanitize_segment(text: str) -> str:
    """Make one path component safe on every platform."""
    text = _ILLEGAL.sub("", text or "").strip()
    text = re.sub(r"\s+", " ", text).strip(". ")
    return text or "untitled"


def build_context(message, chat, author: str | None = None) -> dict[str, Any]:
    date = _local(message.date)
    first_line = (message.message or "").strip().split("\n", 1)[0]
    kind = media_kind(message) or ""
    slug = slugify(first_line) or kind or "message"
    channel_title = getattr(chat, "title", None) or getattr(chat, "username", None) or str(chat.id)
    return {
        "dt": date,
        "date": date.strftime("%Y-%m-%d") if date else "undated",
        "time": date.strftime("%H%M") if date else "0000",
        "datetime": date.strftime("%Y-%m-%d-%H%M") if date else "undated",
        "year": date.strftime("%Y") if date else "0000",
        "month": date.strftime("%m") if date else "00",
        "day": date.strftime("%d") if date else "00",
        "hour": date.strftime("%H") if date else "00",
        "minute": date.strftime("%M") if date else "00",
        "id": message.id,
        "slug": slug,
        "title": first_line[:80] or slug,
        "channel": slugify(channel_title) or f"channel-{chat.id}",
        "channel_title": channel_title,
        "channel_id": chat.id,
        "username": getattr(chat, "username", None) or "",
        "author": author or "",
        "media_type": kind,
    }


def format_template(template: str, ctx: dict[str, Any], *, allow_slash: bool = False) -> str:
    """Render a user template, sanitising each resulting path component."""
    try:
        rendered = template.format(**ctx)
    except KeyError as exc:
        raise TemplateError(
            f"unknown placeholder {exc} in {template!r}; "
            f"available: {', '.join(PLACEHOLDERS)}"
        ) from exc
    except (ValueError, TypeError, AttributeError) as exc:
        raise TemplateError(f"bad template {template!r}: {exc}") from exc

    if not allow_slash:
        rendered = rendered.replace("/", "-")
    parts = [sanitize_segment(p) for p in rendered.split("/") if p.strip()]
    if not parts:
        raise TemplateError(f"template {template!r} produced an empty name")
    return "/".join(parts)


def validate_template(template: str, *, allow_slash: bool = False) -> None:
    """Fail fast at config time rather than mid-sync."""
    probe = {k: (datetime.now() if k == "dt" else 1 if k.endswith("id") else "x")
             for k in PLACEHOLDERS}
    format_template(template, probe, allow_slash=allow_slash)


def message_filename(message, chat, author=None, template: str = DEFAULT_FILENAME) -> str:
    """Default: `2026-07-24-1430-1234-first-words-of-message.md`"""
    name = format_template(template, build_context(message, chat, author))
    return name if name.endswith(".md") else f"{name}.md"


def day_filename(message, chat, author=None, template: str = DEFAULT_DAYFILE) -> str:
    name = format_template(template, build_context(message, chat, author))
    return name if name.endswith(".md") else f"{name}.md"


def channel_folder(message, chat, author=None, template: str = DEFAULT_FOLDER) -> str:
    """Relative folder for a message; may contain `/` for nesting."""
    return format_template(template, build_context(message, chat, author), allow_slash=True)


def render_day_block(message, chat, author: str | None, media_files: list[str]) -> str:
    """One message rendered as a section inside a per-day file."""
    date = _local(message.date)
    time = date.strftime("%H:%M") if date else "??:??"
    link = message_link(chat, message.id)
    heading = f"## {time}" + (f" · [#{message.id}]({link})" if link else f" · #{message.id}")
    if author:
        heading += f" · {author}"
    body = render_body(message, media_files)
    return f"<!-- telesync:{message.id} -->\n{heading}\n\n{body}\n"
