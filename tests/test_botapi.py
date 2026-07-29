"""HTTP Bot API adapters and the reaction helper — no network."""

from types import SimpleNamespace

import pytest

from telesync.botapi import adapt_chat, adapt_message
from telesync.botsync import chat_matches
from telesync.config import Config
from telesync.render import render_body, render_document
from telesync.sync import Reactor

CHAT = {"id": -1001234567890, "title": "My Channel", "username": "mychan", "type": "channel"}


def cfg(tmp_path, **kw):
    base = dict(api_id=None, api_hash=None, session=tmp_path / "s", out_dir=tmp_path)
    base.update(kw)
    return Config(**base)


def test_chat_id_normalised_to_mtproto_form():
    chat = adapt_chat(CHAT)
    assert chat.id == 1234567890          # matches what MTProto reports
    assert chat.bot_api_id == -1001234567890  # what the HTTP API expects back
    assert chat.broadcast is True


def test_group_chat_id_normalised():
    chat = adapt_chat({"id": -4505638899, "title": "Seeding", "type": "group"})
    assert chat.id == 4505638899
    assert chat.bot_api_id == -4505638899
    assert chat.broadcast is False


def test_message_text_and_entities():
    msg = adapt_message({
        "message_id": 7,
        "date": 1_700_000_000,
        "text": "hello world",
        "entities": [
            {"type": "bold", "offset": 0, "length": 5},
            {"type": "text_link", "offset": 6, "length": 5, "url": "https://x.test"},
        ],
    })
    assert render_body(msg, []) == "**hello** [world](https://x.test)"


def test_caption_and_caption_entities_used_for_media():
    msg = adapt_message({
        "message_id": 8,
        "date": 1_700_000_000,
        "caption": "a photo",
        "caption_entities": [{"type": "italic", "offset": 2, "length": 5}],
        "photo": [
            {"file_id": "small", "file_size": 100, "width": 90},
            {"file_id": "big", "file_size": 9000, "width": 1280},
        ],
    })
    assert msg.photo is True
    assert msg._file_id == "big"          # largest size is kept
    assert msg.media is True
    assert render_body(msg, []) == "a *photo*"


def test_frontmatter_from_bot_api_message(tmp_path):
    chat = adapt_chat(CHAT)
    msg = adapt_message({
        "message_id": 12,
        "date": 1_700_000_000,
        "edit_date": 1_700_000_500,
        "text": "hi",
        "author_signature": "Editor",
        "media_group_id": "555",
        "reply_to_message": {"message_id": 11},
    })
    doc = render_document(msg, chat, msg.post_author, [])
    assert "id: 12" in doc
    assert "author: Editor" in doc
    assert "reply_to: 11" in doc
    assert "album: '555'" in doc
    assert "url: https://t.me/mychan/12" in doc


def test_poll_location_contact_adapted():
    poll = adapt_message({
        "message_id": 1, "date": 1_700_000_000,
        "poll": {"question": "Pick one", "options": [{"text": "A"}, {"text": "B"}]},
    })
    body = render_body(poll, [])
    assert "**Poll:** Pick one" in body and "- [ ] A" in body

    loc = adapt_message({
        "message_id": 2, "date": 1_700_000_000,
        "location": {"latitude": 10.5, "longitude": 106.7},
    })
    assert "10.5, 106.7" in render_body(loc, [])

    contact = adapt_message({
        "message_id": 3, "date": 1_700_000_000,
        "contact": {"first_name": "Ada", "phone_number": "+123"},
    })
    assert "**Contact:** Ada  — +123" in render_body(contact, [])


def test_service_only_message_has_no_media_flag():
    msg = adapt_message({"message_id": 4, "date": 1_700_000_000, "text": "plain"})
    assert msg.media is False


@pytest.mark.parametrize(
    "ref",
    ["-1001234567890", "1234567890", "@mychan", "mychan", "My Channel",
     "https://t.me/mychan"],
)
def test_chat_matches_every_ref_form(ref):
    assert chat_matches(adapt_chat(CHAT), [ref]) is True


def test_chat_does_not_match_other_refs():
    assert chat_matches(adapt_chat(CHAT), ["@otherchan", "-1009999999999"]) is False


class FakeBotAPI:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    async def set_reaction(self, chat, message_id, emoji):
        if self.fail:
            raise RuntimeError("REACTION_INVALID")
        self.calls.append((chat.bot_api_id, message_id, emoji))


async def test_reactor_uses_bot_api_id(tmp_path):
    api = FakeBotAPI()
    reactor = Reactor(api, cfg(tmp_path))
    chat = adapt_chat(CHAT)

    assert await reactor.react(chat, 42) is True
    assert api.calls == [(-1001234567890, 42, "\U0001f984")]
    assert reactor.count == 1


async def test_reactor_disabled_by_flag(tmp_path):
    api = FakeBotAPI()
    reactor = Reactor(api, cfg(tmp_path, react=False))
    assert await reactor.react(adapt_chat(CHAT), 1) is False
    assert api.calls == []


async def test_reactor_gives_up_after_first_failure(tmp_path, capsys):
    api = FakeBotAPI(fail=True)
    reactor = Reactor(api, cfg(tmp_path))
    chat = adapt_chat(CHAT)

    assert await reactor.react(chat, 1) is False
    assert reactor.enabled is False
    assert "reactions disabled" in capsys.readouterr().out
    # a rejected reaction must not abort the sync, nor retry every message
    assert await reactor.react(chat, 2) is False


async def test_custom_react_emoji(tmp_path):
    api = FakeBotAPI()
    reactor = Reactor(api, cfg(tmp_path, react_emoji="👍"))
    await reactor.react(adapt_chat(CHAT), 3)
    assert api.calls[0][2] == "👍"


async def test_edited_message_gets_edit_emoji(tmp_path):
    api = FakeBotAPI()
    reactor = Reactor(api, cfg(tmp_path))
    chat = adapt_chat(CHAT)
    await reactor.react(chat, 5)
    await reactor.react(chat, 5, edited=True)
    assert api.calls[0][2] == "\U0001f984"  # 🦄 first sync
    assert api.calls[1][2] == "\U0001f47e"  # 👾 re-sync after edit


async def test_network_timeout_wrapped_in_botapi_error(monkeypatch):
    from telesync import botapi

    def boom(*args, **kwargs):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(botapi.urllib.request, "urlopen", boom)
    with pytest.raises(botapi.BotAPIError, match="timed out"):
        await botapi.BotAPI("1:x").call("getUpdates")


async def test_custom_edit_emoji(tmp_path):
    api = FakeBotAPI()
    reactor = Reactor(api, cfg(tmp_path, react_edit_emoji="🔁"))
    await reactor.react(adapt_chat(CHAT), 6, edited=True)
    assert api.calls[0][2] == "🔁"
