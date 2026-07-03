from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ScrumpokerAPI.main  import app
from ScrumpokerAPI.room_manager import room_manager
from ScrumpokerAPI.room import Room
from ScrumpokerAPI.models import Vote


@pytest.fixture(autouse=True)
def reset_rooms():
    room_manager.rooms.clear()
    yield
    room_manager.rooms.clear()


def test_get_active_rooms_empty():
    with TestClient(app) as client:
        response = client.get("/rooms")
        assert response.status_code == 200
        assert response.json() == {}


def test_get_active_rooms_serializes_room_state():
    """Regression test for the bug where raw Voter objects and Vote
    pydantic models were passed straight into JSONResponse — Voter isn't
    even a pydantic model (it holds a live WebSocket), so the endpoint
    would have failed to serialize on first real call."""
    room = Room("demo")
    room.voters.append(SimpleNamespace(display_name="Alice"))
    room.votes["voter-1"] = Vote(voter="voter-1", vote="5")
    room.reveal = True
    room.votingCard = "Fibonacci"
    room_manager.rooms["demo"] = room

    with TestClient(app) as client:
        response = client.get("/rooms")

    assert response.status_code == 200
    data = response.json()
    assert data["demo"]["connected_users"] == ["Alice"]
    assert data["demo"]["votes"]["voter-1"]["vote"] == "5"
    assert data["demo"]["reveal"] is True
    assert data["demo"]["votingCard"] == "Fibonacci"


def test_get_active_rooms_lists_multiple_rooms():
    room_manager.rooms["room-a"] = Room("room-a")
    room_manager.rooms["room-b"] = Room("room-b")

    with TestClient(app) as client:
        response = client.get("/rooms")

    assert set(response.json().keys()) == {"room-a", "room-b"}