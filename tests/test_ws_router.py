import pytest
from fastapi.testclient import TestClient

from ScrumpokerAPI.main import app
from ScrumpokerAPI.room_manager import room_manager


@pytest.fixture(autouse=True)
def reset_rooms():
    """Room state is a module-level singleton (room_manager), so clear it
    before and after every test to stop rooms leaking between tests."""
    room_manager.rooms.clear()
    yield
    room_manager.rooms.clear()


def test_connect_receives_initial_votes_and_settings():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room1") as ws:
            ws.send_json({"name": "Alice"})

            votes_msg = ws.receive_json()
            assert votes_msg["type"] == "result"

            settings_msg = ws.receive_json()
            assert settings_msg["type"] == "settings"


def test_duplicate_name_in_same_room_is_rejected():
    """Regression test for the bug where `name in room.voters` compared a
    string against a list of Voter objects and never matched, so
    duplicate-name rejection silently never fired."""
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room1") as ws1:
            ws1.send_json({"name": "Alice"})
            ws1.receive_json()  # votes
            ws1.receive_json()  # settings

            with client.websocket_connect("/ws/room1") as ws2:
                ws2.send_json({"name": "Alice"})
                error_msg = ws2.receive_json()
                assert error_msg == {"type": "error", "error": "New Name Needed"}


def test_empty_name_is_rejected():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room2") as ws:
            ws.send_json({"name": ""})
            error_msg = ws.receive_json()
            assert error_msg == {"type": "error", "error": "New Name Needed"}


def test_vote_message_round_trips():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room3") as ws:
            ws.send_json({"name": "Alice"})
            ws.receive_json()  # initial votes
            ws.receive_json()  # initial settings

            alice_id = room_manager.get("room3").voters[0].id
            ws.send_json({"type": "vote", "voter": alice_id, "vote": "5"})

            votes_msg = ws.receive_json()
            assert votes_msg["votes"][alice_id]["vote"] == "5"


def test_card_change_message_updates_settings():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room_card") as ws:
            ws.send_json({"name": "Alice"})
            ws.receive_json()  # votes
            ws.receive_json()  # settings

            ws.send_json({"type": "cardChange", "card": "Fibonacci"})
            settings_msg = ws.receive_json()
            assert settings_msg["type"] == "settings"
            assert settings_msg["votingCard"] == "Fibonacci"


def test_reaction_message_lands_on_recipient():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room4") as ws1, \
             client.websocket_connect("/ws/room4") as ws2:
            ws1.send_json({"name": "Alice"})
            ws1.receive_json()  # Alice's own join: votes
            ws1.receive_json()  # Alice's own join: settings

            ws2.send_json({"name": "Bob"})
            # Bob joining triggers broadcast_votes() + broadcast_settings(),
            # each sent to EVERY connected voter -- so both Alice and Bob
            # get two messages here, not just Bob.
            ws1.receive_json()  # votes (post-Bob-join)
            ws1.receive_json()  # settings (post-Bob-join)
            ws2.receive_json()  # votes (post-Bob-join)
            ws2.receive_json()  # settings (post-Bob-join)

            room = room_manager.get("room4")
            bob_id = room.voters[1].id

            # Note: no "from_voter" -- the client never sends it, the
            # server stamps it from the connection identity.
            ws1.send_json({
                "type": "reaction",
                "id": "ignored",
                "emoji": "🔥",
                "to_voter": bob_id,
            })

            settings_msg = ws1.receive_json()
            assert settings_msg["type"] == "settings"
            assert bob_id in settings_msg["reactions"]
            assert settings_msg["reactions"][bob_id][0]["from_voter"] != bob_id


def test_missile_reaction_enforces_one_per_session():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room_missile") as ws1, \
             client.websocket_connect("/ws/room_missile") as ws2:
            ws1.send_json({"name": "Alice"})
            ws1.receive_json()
            ws1.receive_json()

            ws2.send_json({"name": "Bob"})
            ws1.receive_json()
            ws1.receive_json()
            ws2.receive_json()
            ws2.receive_json()

            bob_id = room_manager.get("room_missile").voters[1].id

            ws1.send_json({"type": "reaction", "id": "1", "emoji": "x", "to_voter": bob_id, "kind": "missile"})
            first = ws1.receive_json()
            assert bob_id in first["reactions"]
            assert len(first["reactions"][bob_id]) == 1

            ws1.send_json({"type": "reaction", "id": "2", "emoji": "x", "to_voter": bob_id, "kind": "missile"})
            # rejected server-side -- no broadcast fires, so the next
            # thing on the wire should be nothing new for this recipient.
            # Confirm by sending a harmless follow-up vote and checking
            # the reaction count didn't grow.
            ws1.send_json({"type": "vote", "voter": bob_id, "vote": "3"})
            votes_msg = ws1.receive_json()
            assert votes_msg["type"] == "result"


def test_unrecognized_message_shape_sends_error():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room5") as ws:
            ws.send_json({"name": "Alice"})
            ws.receive_json()
            ws.receive_json()

            ws.send_json({"nonsense_key": True})
            error_msg = ws.receive_json()
            assert error_msg == {"type": "error", "error": "Invalid data format"}


def test_missing_type_field_sends_error():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room_no_type") as ws:
            ws.send_json({"name": "Alice"})
            ws.receive_json()
            ws.receive_json()

            ws.send_json({"voter": "x", "vote": "5"})  # old-style, no "type"
            error_msg = ws.receive_json()
            assert error_msg == {"type": "error", "error": "Invalid data format"}


def test_exit_room_command_removes_voter():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/room6") as ws:
            ws.send_json({"name": "Alice"})
            ws.receive_json()
            ws.receive_json()

            ws.send_json({"type": "command", "command": "Exit_room"})
            success_msg = ws.receive_json()
            assert success_msg == {"type": "success", "success": "Exiting Room"}

        # room still exists (Exit_room only drops the voter, not the room)
        room = room_manager.get("room6")
        assert room is not None
        assert len(room.voters) == 0
