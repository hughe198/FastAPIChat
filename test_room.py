import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from starlette.websockets import WebSocketState

from ScrumpokerAPI.room import Room, Reaction


class FakeWebSocket:
    """Minimal stand-in for a starlette WebSocket.

    Room only ever calls `await websocket.send_json(...)`, `await
    websocket.close(...)`, and reads `.client_state`, so that's all this
    needs to fake. Using a real object (not just `object()`) because Room
    compares with `is`, and because connect/broadcast now touch these
    methods directly instead of a separate voterSocket/connections list.
    """
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.send_json = AsyncMock()
        self.close = AsyncMock()


@pytest.fixture
def room():
    return Room(room_id="test_room", ttl=3600)


def make_ws():
    return FakeWebSocket()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_room_initialization(room):
    assert room.roomID == "test_room"
    assert room.reveal is False
    assert room.votingCard == "Standard"
    assert room.votes == {}
    assert room.voters == []
    assert room.settings.reveal is False
    assert room.settings.votingCard == "Standard"
    assert room.settings.reactions == {}
    assert room.settings.missile_used_by == set()


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_voter(room):
    websocket = make_ws()
    await room.connect(websocket, "Alice")

    assert len(room.voters) == 1
    voter = room.voters[0]
    assert voter.display_name == "Alice"
    assert voter.webSocket is websocket
    # connect() casts an initial empty vote for the new voter
    assert len(room.votes) == 1
    assert room.votes[voter.id].vote == ""
    # both votes and settings are pushed out on join
    websocket.send_json.assert_awaited()


@pytest.mark.asyncio
async def test_duplicate_display_names_are_allowed_server_side(room):
    """Room itself does not enforce unique display names — dedup happens
    on the frontend. This test documents that behavior rather than
    asserting a rejection that the server no longer performs, so a future
    change to this doesn't get silently un-tested."""
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Alice")

    assert len(room.voters) == 2
    assert {v.display_name for v in room.voters} == {"Alice"}
    # each gets a distinct id despite the same display name
    assert room.voters[0].id != room.voters[1].id


@pytest.mark.asyncio
async def test_remove_voter(room):
    websocket = make_ws()
    await room.connect(websocket, "Alice")
    voter_id = room.voters[0].id

    await room.disconnect(websocket)

    assert len(room.voters) == 0
    assert voter_id not in room.votes
    assert voter_id not in room.settings.reactions
    websocket.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_removes_pending_reactions_for_that_voter(room):
    """test_remove_voter only covers a voter with no reactions against
    them. This covers the case where settings.reactions actually has a
    non-empty entry at disconnect time, confirming the .pop() cleans up
    real data and not just an absent key."""
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id = room.voters[0].id
    bob_id = room.voters[1].id

    # Bob receives reactions from Alice while still connected
    room.add_reaction(Reaction(id="a", emoji="👍", from_voter=alice_id, to_voter=bob_id))
    room.add_reaction(Reaction(id="b", emoji="👀", from_voter=alice_id, to_voter=bob_id))
    assert bob_id in room.settings.reactions
    assert len(room.settings.reactions[bob_id]) == 2

    await room.disconnect(ws2)  # Bob leaves

    assert bob_id not in room.settings.reactions
    # Alice's own state is untouched — only the departing voter's entry is cleared
    assert len(room.voters) == 1
    assert room.voters[0].id == alice_id


@pytest.mark.asyncio
async def test_disconnect_all(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")

    await room.disconnect_all()

    ws1.close.assert_awaited_once()
    ws2.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# TTL / activity
# ---------------------------------------------------------------------------

def test_is_expired(room):
    room.last_activity = datetime.now() - timedelta(seconds=3601)
    assert room.is_expired() is True

    room.reset_activity()
    assert room.is_expired() is False


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_votes_resets_reactions_and_missile(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id = room.voters[0].id
    bob_id = room.voters[1].id

    room.votes[alice_id].vote = "5"
    room.settings.reactions[bob_id] = [
        Reaction(id="r1", emoji="👍", from_voter=alice_id, to_voter=bob_id)
    ]
    room.settings.missile_used_by.add(alice_id)

    room.clear_votes()

    assert room.votes[alice_id].vote == ""
    assert room.settings.reactions == {}
    assert room.settings.missile_used_by == set()


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_reaction_success(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id = room.voters[0].id
    bob_id = room.voters[1].id

    reaction = Reaction(id="client-supplied", emoji="🔥", from_voter=alice_id, to_voter=bob_id)
    result = room.add_reaction(reaction)

    assert result is not None
    assert bob_id in room.settings.reactions
    assert len(room.settings.reactions[bob_id]) == 1
    stored = room.settings.reactions[bob_id][0]
    assert stored.from_voter == alice_id
    assert stored.emoji == "🔥"
    # server should re-generate the id rather than trust the client's
    assert stored.id != "client-supplied"


@pytest.mark.asyncio
async def test_add_reaction_unknown_target_returns_none(room):
    ws1 = make_ws()
    await room.connect(ws1, "Alice")
    alice_id = room.voters[0].id

    reaction = Reaction(id="x", emoji="🔥", from_voter=alice_id, to_voter="not-a-real-voter-id")
    result = room.add_reaction(reaction)

    assert result is None
    assert room.settings.reactions == {}


@pytest.mark.asyncio
async def test_add_reaction_multiple_stack_for_same_recipient(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id = room.voters[0].id
    bob_id = room.voters[1].id

    room.add_reaction(Reaction(id="a", emoji="👍", from_voter=alice_id, to_voter=bob_id))
    room.add_reaction(Reaction(id="b", emoji="👀", from_voter=alice_id, to_voter=bob_id))

    assert len(room.settings.reactions[bob_id]) == 2


# ---------------------------------------------------------------------------
# Missile strike
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fire_missile_success(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id = room.voters[0].id
    bob_id = room.voters[1].id

    reaction = Reaction(id="ignored", emoji="ignored", from_voter=alice_id, to_voter=bob_id, kind="missile")
    result = room.fire_missile(reaction)

    assert result is not None
    assert result.emoji == "💥"
    assert result.kind == "missile"
    assert alice_id in room.settings.missile_used_by
    assert len(room.settings.reactions[bob_id]) == 1


@pytest.mark.asyncio
async def test_fire_missile_rejects_second_use(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id = room.voters[0].id
    bob_id = room.voters[1].id

    first = room.fire_missile(Reaction(id="1", emoji="x", from_voter=alice_id, to_voter=bob_id, kind="missile"))
    second = room.fire_missile(Reaction(id="2", emoji="x", from_voter=alice_id, to_voter=bob_id, kind="missile"))

    assert first is not None
    assert second is None
    # only the first missile's reaction should have landed
    assert len(room.settings.reactions[bob_id]) == 1


@pytest.mark.asyncio
async def test_fire_missile_unknown_target_returns_none(room):
    ws1 = make_ws()
    await room.connect(ws1, "Alice")
    alice_id = room.voters[0].id

    reaction = Reaction(id="1", emoji="x", from_voter=alice_id, to_voter="ghost-id", kind="missile")
    result = room.fire_missile(reaction)

    assert result is None
    assert alice_id not in room.settings.missile_used_by


@pytest.mark.asyncio
async def test_clear_votes_allows_missile_reuse(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id = room.voters[0].id
    bob_id = room.voters[1].id

    room.fire_missile(Reaction(id="1", emoji="x", from_voter=alice_id, to_voter=bob_id, kind="missile"))
    assert alice_id in room.settings.missile_used_by

    room.clear_votes()
    assert alice_id not in room.settings.missile_used_by

    second = room.fire_missile(Reaction(id="2", emoji="x", from_voter=alice_id, to_voter=bob_id, kind="missile"))
    assert second is not None


# ---------------------------------------------------------------------------
# Sender identity lookup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_sender_id_matches_connected_voter(room):
    websocket = make_ws()
    await room.connect(websocket, "Alice")
    voter_id = room.voters[0].id

    assert room.get_sender_id(websocket) == voter_id


def test_get_sender_id_unknown_socket_returns_none(room):
    """get_sender_id should not raise for a socket it doesn't recognize —
    e.g. a message arriving in the brief window after disconnect starts
    removing the voter but before the socket is fully closed."""
    websocket = make_ws()
    assert room.get_sender_id(websocket) is None