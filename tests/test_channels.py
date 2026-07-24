"""Channel-reference resolution and the saved channel list — no network."""

from argparse import Namespace
from types import SimpleNamespace

import pytest

from telesync.cli import resolve_channel_refs
from telesync.config import Config, ConfigError, load_config
from telesync.state import State
from telesync.sync import ChannelNotFound, resolve_channel


def chat(cid, title, username=None):
    return SimpleNamespace(id=cid, title=title, username=username)


class FakeClient:
    """Minimal stand-in for TelegramClient."""

    def __init__(self, entities=None, dialogs=(), is_bot=False):
        self.entities = entities or {}
        self.dialogs = list(dialogs)
        self._is_bot = is_bot
        self.dialog_scans = 0

    async def is_bot(self):
        return self._is_bot

    async def get_entity(self, ref):
        if ref in self.entities:
            return self.entities[ref]
        raise ValueError(f"cannot find {ref}")

    def iter_dialogs(self):
        self.dialog_scans += 1
        entries = self.dialogs

        async def gen():
            for entity in entries:
                yield SimpleNamespace(name=entity.title, entity=entity)

        return gen()


@pytest.mark.asyncio
async def test_resolve_by_username_and_link():
    durov = chat(1, "Durov", "durov")
    client = FakeClient(entities={"durov": durov})
    assert await resolve_channel(client, "@durov") is durov
    assert await resolve_channel(client, "https://t.me/durov") is durov
    assert await resolve_channel(client, "t.me/s/durov") is durov


@pytest.mark.asyncio
async def test_resolve_by_numeric_id():
    private = chat(-1001234567890, "Private")
    client = FakeClient(entities={-1001234567890: private})
    assert await resolve_channel(client, "-1001234567890") is private


@pytest.mark.asyncio
async def test_resolve_by_display_name():
    target = chat(5, "My Private Notes")
    client = FakeClient(dialogs=[chat(4, "Other"), target])
    assert await resolve_channel(client, "My Private Notes") is target
    # case-insensitive substring also works
    assert await resolve_channel(client, "private notes") is target


@pytest.mark.asyncio
async def test_username_lookup_wins_before_dialog_scan():
    named = chat(9, "durov")
    client = FakeClient(entities={"durov": named}, dialogs=[chat(10, "durov backup")])
    assert await resolve_channel(client, "durov") is named
    assert client.dialog_scans == 0


@pytest.mark.asyncio
async def test_ambiguous_name_rejected():
    client = FakeClient(dialogs=[chat(1, "News Daily"), chat(2, "News Weekly")])
    with pytest.raises(ChannelNotFound, match="ambiguous"):
        await resolve_channel(client, "News")


@pytest.mark.asyncio
async def test_unknown_name_reports_clearly():
    client = FakeClient(dialogs=[chat(1, "Something")])
    with pytest.raises(ChannelNotFound, match="no chat named"):
        await resolve_channel(client, "Nothing Like This")


@pytest.mark.asyncio
async def test_bot_cannot_resolve_names():
    client = FakeClient(is_bot=True)
    with pytest.raises(ChannelNotFound, match="numeric channel ids"):
        await resolve_channel(client, "Some Channel")


def test_state_subscriptions_roundtrip(tmp_path):
    state = State.load(tmp_path)
    assert state.subscribe("@durov") is True
    assert state.subscribe("@durov") is False
    state.save()

    reloaded = State.load(tmp_path)
    assert reloaded.subscriptions() == ["@durov"]
    assert reloaded.unsubscribe("DUROV") is True   # case/@-insensitive
    assert reloaded.unsubscribe("@durov") is False


def test_cli_channels_override_saved_list(tmp_path):
    state = State.load(tmp_path)
    state.subscribe("@saved")
    cfg = Config(
        api_id=1, api_hash="x", session=tmp_path / "s", out_dir=tmp_path,
        channels=["@fromcli"], channels_from_cli=True,
    )
    assert resolve_channel_refs(cfg, state) == ["@fromcli"]

    cfg.channels_from_cli = False
    cfg.channels = ["@fromenv", "@saved"]
    assert resolve_channel_refs(cfg, state) == ["@saved", "@fromenv"]


def _args(**kw):
    base = dict(env_file="/nonexistent.env", out=None, session=None, channel=None,
                layout=None, media=False, recheck=0, bot_token=None)
    base.update(kw)
    return Namespace(**base)


def test_bot_token_uses_separate_session(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.delenv("TELEGRAM_SESSION", raising=False)

    user_cfg = load_config(_args())
    bot_cfg = load_config(_args(bot_token="123456:AA" + "x" * 33))

    assert user_cfg.is_bot is False
    assert bot_cfg.is_bot is True
    assert user_cfg.session != bot_cfg.session
    assert bot_cfg.session.name == "telesync-bot.session"


def test_malformed_bot_token_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    with pytest.raises(ConfigError, match="malformed"):
        load_config(_args(bot_token="not-a-token"))


def test_missing_credentials_rejected(monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    with pytest.raises(ConfigError, match="my.telegram.org"):
        load_config(_args())
