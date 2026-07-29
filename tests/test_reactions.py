"""reaction_target: which raw reaction updates trigger a (re)write."""

from datetime import datetime, timezone

from telethon.tl import types

from telesync.sync import reaction_target

BOT_ID = 999
NOW = datetime(2026, 7, 24, tzinfo=timezone.utc)
THUMBS = types.ReactionEmoji(emoticon="👍")


def bot_reaction(actor_id: int, new_reactions: list, chat_id: int = 42, msg_id: int = 7):
    return types.UpdateBotMessageReaction(
        peer=types.PeerChat(chat_id=chat_id),
        msg_id=msg_id,
        date=NOW,
        actor=types.PeerUser(user_id=actor_id),
        old_reactions=[],
        new_reactions=new_reactions,
        qts=1,
    )


def user_reaction(results: list, chat_id: int = 42, msg_id: int = 7):
    return types.UpdateMessageReactions(
        peer=types.PeerChat(chat_id=chat_id),
        msg_id=msg_id,
        reactions=types.MessageReactions(results=results),
    )


def test_bot_reaction_from_someone_else_triggers():
    update = bot_reaction(actor_id=111, new_reactions=[THUMBS])
    assert reaction_target(update, self_id=BOT_ID) == (-42, 7)


def test_bot_reaction_from_self_is_ignored():
    update = bot_reaction(actor_id=BOT_ID, new_reactions=[THUMBS])
    assert reaction_target(update, self_id=BOT_ID) is None


def test_bot_reaction_removal_is_ignored():
    update = bot_reaction(actor_id=111, new_reactions=[])
    assert reaction_target(update, self_id=BOT_ID) is None


def test_user_reaction_triggers():
    results = [types.ReactionCount(reaction=THUMBS, count=1)]
    assert reaction_target(user_reaction(results), self_id=BOT_ID) == (-42, 7)


def test_user_reaction_removal_is_ignored():
    assert reaction_target(user_reaction([]), self_id=BOT_ID) is None


def test_channel_peer_gets_marked_id():
    update = types.UpdateMessageReactions(
        peer=types.PeerChannel(channel_id=123),
        msg_id=9,
        reactions=types.MessageReactions(results=[types.ReactionCount(reaction=THUMBS, count=2)]),
    )
    assert reaction_target(update) == (-1000000000123, 9)


def test_unrelated_update_is_ignored():
    assert reaction_target(types.UpdateUserTyping(
        user_id=1, action=types.SendMessageTypingAction()
    )) is None
