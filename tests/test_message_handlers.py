import pytest

from ScrumpokerAPI.room import Room
from ScrumpokerAPI.room_manager import RoomManager
from ScrumpokerAPI.message_handlers import (
    handle_command,
    handle_card_change,
    handle_vote,
    handle_settings,
    handle_reaction,
)
from test_helpers import make_ws


@pytest.fixture
def room():
    return Room(room_id="test_room", ttl=3600)


@pytest.fixture
def manager(room):
    m = RoomManager()
    m.rooms["test_room"] = room
    return m


# ---------------------------------------------------------------------------
# handle_command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clear_votes_resets_votes_and_broadcasts(room, manager):
    ws = make_ws()
    await room.connect(ws, "Alice")
    alice_id = room.voters[0].id
    room.votes[alice_id].vote = "5"
    ws.send_json.reset_mock()

    should_stop = await handle_command(room, ws, {"command": "Clear_votes"}, "test_room", manager)

    assert should_stop is False
    assert room.votes[alice_id].vote == ""
    ws.send_json.assert_awaited()


@pytest.mark.asyncio
async def test_delete_room_existing_room(room, manager):
    ws = make_ws()
    await room.connect(ws, "Alice")
    ws.send_json.reset_mock()

    should_stop = await handle_command(room, ws, {"command": "Delete_room"}, "test_room", manager)

    assert should_stop is True
    assert manager.get("test_room") is None
    ws.send_json.assert_any_await({"type": "success", "success": "Room Deleted"})


@pytest.mark.asyncio
async def test_delete_room_missing_room_sends_error(room):
    ws = make_ws()
    empty_manager = RoomManager()  # "test_room" was never registered

    should_stop = await handle_command(room, ws, {"command": "Delete_room"}, "test_room", empty_manager)

    assert should_stop is True
    ws.send_json.assert_any_await({"type": "error", "error": "Room doesn't exist"})


@pytest.mark.asyncio
async def test_reveal_votes_toggles_reveal_flag(room, manager):
    ws = make_ws()
    await room.connect(ws, "Alice")
    assert room.reveal is False

    should_stop = await handle_command(room, ws, {"command": "Reveal_votes"}, "test_room", manager)

    assert should_stop is False
    assert room.reveal is True


@pytest.mark.asyncio
async def test_exit_room_disconnects_sender_only(room, manager):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    ws1.send_json.reset_mock()

    should_stop = await handle_command(room, ws1, {"command": "Exit_room"}, "test_room", manager)

    assert should_stop is True
    assert len(room.voters) == 1
    assert room.voters[0].display_name == "Bob"
    ws1.send_json.assert_any_await({"type": "success", "success": "Exiting Room"})


@pytest.mark.asyncio
async def test_unknown_command_sends_error_and_continues(room, manager):
    ws = make_ws()
    should_stop = await handle_command(room, ws, {"command": "Not_A_Real_Command"}, "test_room", manager)

    assert should_stop is False
    ws.send_json.assert_any_await({"type": "error", "error": "Unknown Command"})


# ---------------------------------------------------------------------------
# handle_card_change
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_card_change_updates_voting_card(room):
    ws = make_ws()
    await handle_card_change(room, ws, {"type": "cardChange", "card": "Fibonacci"})
    assert room.votingCard == "Fibonacci"


# ---------------------------------------------------------------------------
# handle_vote
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_vote_valid_updates_and_broadcasts(room):
    ws = make_ws()
    await room.connect(ws, "Alice")
    alice_id = room.voters[0].id
    ws.send_json.reset_mock()

    await handle_vote(room, ws, {"voter": alice_id, "vote": "8"})

    assert room.votes[alice_id].vote == "8"
    ws.send_json.assert_awaited()


@pytest.mark.asyncio
async def test_handle_vote_missing_field_sends_error(room):
    ws = make_ws()
    await handle_vote(room, ws, {"voter": "someone"})  # missing "vote"

    sent = ws.send_json.await_args.args[0]
    assert sent["type"] == "error"
    assert sent["error"] == "Invalid vote data format or missing fields"


# ---------------------------------------------------------------------------
# handle_settings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_settings_valid_broadcasts(room):
    ws = make_ws()
    await room.connect(ws, "Alice")
    ws.send_json.reset_mock()

    await handle_settings(room, ws, {"reveal": True, "votingCard": "Standard"})

    assert room.reveal is True


@pytest.mark.asyncio
async def test_handle_settings_missing_field_sends_error(room):
    ws = make_ws()
    await handle_settings(room, ws, {"reveal": True})  # missing "votingCard"

    sent = ws.send_json.await_args.args[0]
    assert sent["type"] == "error"
    assert sent["error"] == "Invalid settings data format or missing fields"


# ---------------------------------------------------------------------------
# handle_reaction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_reaction_normal_stamps_sender_and_broadcasts(room):
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id, bob_id = room.voters[0].id, room.voters[1].id

    # Note: no "from_voter" in the payload at all -- the client never
    # sends it, the server stamps it from the connection identity.
    await handle_reaction(room, ws1, {
        "type": "reaction",
        "id": "client-supplied",
        "emoji": "🔥",
        "to_voter": bob_id,
    })

    assert bob_id in room.settings.reactions
    stored = room.settings.reactions[bob_id][0]
    assert stored.from_voter == alice_id


@pytest.mark.asyncio
async def test_handle_reaction_missile_kind_routes_to_fire_missile(room):
    """Regression test for the bug where missile-kind reactions were
    always routed through add_reaction, so the one-per-session limit
    never engaged."""
    ws1, ws2 = make_ws(), make_ws()
    await room.connect(ws1, "Alice")
    await room.connect(ws2, "Bob")
    alice_id, bob_id = room.voters[0].id, room.voters[1].id

    await handle_reaction(room, ws1, {
        "type": "reaction", "id": "x", "emoji": "x", "to_voter": bob_id, "kind": "missile",
    })

    assert alice_id in room.settings.missile_used_by
    assert room.settings.reactions[bob_id][0].kind == "missile"


@pytest.mark.asyncio
async def test_handle_reaction_unrecognized_sender_is_dropped_silently(room):
    ws = make_ws()  # never connected, so get_sender_id can't find it

    await handle_reaction(room, ws, {"type": "reaction", "id": "x", "emoji": "x", "to_voter": "y"})

    ws.send_json.assert_not_awaited()
    assert room.settings.reactions == {}


@pytest.mark.asyncio
async def test_handle_reaction_invalid_payload_sends_error(room):
    ws = make_ws()
    await room.connect(ws, "Alice")
    ws.send_json.reset_mock()

    await handle_reaction(room, ws, {"type": "reaction", "emoji": "🔥"})  # missing to_voter

    sent = ws.send_json.await_args.args[0]
    assert sent["type"] == "error"
    assert sent["error"] == "Invalid reaction data format or missing fields"
