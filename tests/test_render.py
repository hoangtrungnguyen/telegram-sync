"""Offline tests — no Telegram connection required."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from telethon.tl import types

from telesync.render import (
    TemplateError,
    channel_folder,
    entities_to_markdown,
    message_filename,
    slugify,
    validate_template,
)
from telesync.sync import write_per_day, write_per_message


def fake_message(text="", entities=None, mid=1, date=None, **kw):
    msg = SimpleNamespace(
        id=mid,
        message=text,
        entities=entities or [],
        date=date or datetime(2026, 7, 24, 7, 30, tzinfo=timezone.utc),
        edit_date=None,
        views=None,
        forwards=None,
        reply_to=None,
        grouped_id=None,
        photo=None, video=None, voice=None, video_note=None, audio=None,
        sticker=None, gif=None, document=None, web_preview=None, poll=None,
        geo=None, contact=None, media=None,
    )
    for k, v in kw.items():
        setattr(msg, k, v)
    return msg


def fake_chat():
    return SimpleNamespace(id=100500, title="Test Channel", username="testchan")


def test_bold_and_italic():
    text = "hello world"
    ents = [
        types.MessageEntityBold(offset=0, length=5),
        types.MessageEntityItalic(offset=6, length=5),
    ]
    assert entities_to_markdown(text, ents) == "**hello** *world*"


def test_nested_entities():
    text = "abcdef"
    ents = [
        types.MessageEntityBold(offset=0, length=6),
        types.MessageEntityItalic(offset=2, length=2),
    ]
    assert entities_to_markdown(text, ents) == "**ab*cd*ef**"


def test_utf16_offsets_with_emoji():
    # 😀 is two UTF-16 code units; a naive str-index implementation misplaces the bold.
    text = "😀 bold here"
    ents = [types.MessageEntityBold(offset=3, length=4)]
    assert entities_to_markdown(text, ents) == "😀 **bold** here"


def test_text_url():
    text = "click me"
    ents = [types.MessageEntityTextUrl(offset=0, length=5, url="https://x.test")]
    assert entities_to_markdown(text, ents) == "[click](https://x.test) me"


def test_blockquote_prefixes_each_line():
    text = "one\ntwo\nafter"
    ents = [types.MessageEntityBlockquote(offset=0, length=7)]
    assert entities_to_markdown(text, ents) == "> one\n> two\nafter"


def test_pre_block_with_language():
    text = "x = 1"
    ents = [types.MessageEntityPre(offset=0, length=5, language="python")]
    assert entities_to_markdown(text, ents) == "\n```python\nx = 1\n```\n"


def test_no_entities_passthrough():
    assert entities_to_markdown("plain", []) == "plain"
    assert entities_to_markdown("", None) == ""


def test_slugify():
    assert slugify("Hello, World! Café") == "hello-world-cafe"
    assert slugify("") == ""


def test_filename_shape():
    msg = fake_message("First line\nsecond", mid=42)
    name = message_filename(msg, fake_chat())
    assert name.endswith("-42-first-line.md")
    assert name[:4] == "2026"


def test_custom_filename_and_folder_templates():
    msg = fake_message("Weekly digest", mid=9)
    chat = fake_chat()
    assert message_filename(msg, chat, None, "{id} - {title}") == "9 - Weekly digest.md"
    assert channel_folder(msg, chat, None, "{channel}/{year}/{month}") == "test-channel/2026/07"
    # strftime specs work through {dt}
    assert channel_folder(msg, chat, None, "{dt:%Y-W%W}") == "2026-W29"


def test_template_sanitises_illegal_characters():
    msg = fake_message("re: a/b <c> | d?", mid=3)
    name = message_filename(msg, fake_chat(), None, "{id} {title}")
    assert name == "3 re a-b c d.md"   # `:<>|?` dropped, `/` folded, spaces collapsed
    assert "/" not in name[:-3]


def test_unknown_placeholder_is_reported():
    with pytest.raises(TemplateError, match="unknown placeholder"):
        validate_template("{nope}-{id}")
    with pytest.raises(TemplateError, match="unknown placeholder"):
        message_filename(fake_message("x"), fake_chat(), None, "{nope}")


def test_template_cannot_produce_empty_name():
    with pytest.raises(TemplateError, match="empty name"):
        message_filename(fake_message(""), fake_chat(), None, "{author}")


def test_per_message_write_respects_folder_nesting(tmp_path):
    msg = fake_message("hello", mid=5)
    chat = fake_chat()
    folder = channel_folder(msg, chat, None, "{channel}/{year}/{month}")
    path = write_per_message(msg, chat, None, [], tmp_path / folder)
    assert path.relative_to(tmp_path).parts[:3] == ("test-channel", "2026", "07")
    assert path.exists()


def test_stale_cleanup_does_not_match_id_prefixes(tmp_path):
    chat = fake_chat()
    write_per_message(fake_message("a", mid=274), chat, None, [], tmp_path)
    write_per_message(fake_message("b", mid=2740), chat, None, [], tmp_path)
    # rewriting 274 must not delete the note for 2740
    write_per_message(fake_message("a edited", mid=274), chat, None, [], tmp_path)
    assert len(list(tmp_path.glob("*.md"))) == 2


def test_per_message_write_replaces_stale_slug(tmp_path):
    chat = fake_chat()
    msg = fake_message("original text", mid=7)
    first = write_per_message(msg, chat, "Author", [], tmp_path)
    assert first.exists()

    edited = fake_message("edited text", mid=7)
    second = write_per_message(edited, chat, "Author", [], tmp_path)

    assert second.exists()
    assert not first.exists()
    assert len(list(tmp_path.glob("*.md"))) == 1
    assert "edited text" in second.read_text()


def test_per_day_merges_and_orders(tmp_path):
    chat = fake_chat()
    later = fake_message("second msg", mid=20)
    earlier = fake_message("first msg", mid=10)

    path = write_per_day(later, chat, None, [], tmp_path)
    write_per_day(earlier, chat, None, [], tmp_path)

    content = path.read_text()
    assert content.count("<!-- telesync:") == 2
    assert content.index("first msg") < content.index("second msg")

    # re-writing an existing id updates in place instead of duplicating
    write_per_day(fake_message("first msg edited", mid=10), chat, None, [], tmp_path)
    content = path.read_text()
    assert content.count("<!-- telesync:") == 2
    assert "first msg edited" in content


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
