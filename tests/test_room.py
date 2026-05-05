import pytest
from datetime import datetime, timedelta
from ScrumpokerAPI.room import Room

@pytest.fixture
def room():
    return Room(roomID="test_room", ttl=3600)

def test_room_initialization(room):
    assert room.roomID == "test_room"
    assert room.reveal is False
    assert room.votingCard == "Standard"
    assert room.votes == {}
    assert room.connections == []
    assert room.voters == []
    assert room.voterSocket == {}

def test_add_voter(room):
    websocket = object()
    name = "Alice"
    result, message = room.connect(websocket, name)
    assert result is True
    assert message == f"User {name} exited room {room.roomID}."
    assert len(room.voters) == 1
    assert len(room.connections) == 1
    assert len(room.votes) == 1
    assert room.voterSocket[websocket] == name

def test_add_duplicate_voter(room):
    websocket = object()
    name = "Alice"
    result, message = room.connect(websocket, name)
    assert result is True
    result, message = room.connect(object(), name)
    assert result is False
    assert message == f"Duplicate name {name} detected, connection rejected."
    assert len(room.voters) == 1
    assert len(room.connections) == 1

def test_remove_voter(room):
    websocket = object()
    name = "Alice"
    room.connect(websocket, name)
    room.disconnect(websocket)
    assert len(room.voters) == 0
    assert len(room.connections) == 0
    assert len(room.votes) == 0
    assert websocket not in room.voterSocket

def test_disconnect_all(room):
    websocket1 = object()
    websocket2 = object()
    name1 = "Alice"
    name2 = "Bob"
    room.connect(websocket1, name1)
    room.connect(websocket2, name2)
    room.disconnect_all()
    assert len(room.voters) == 0
    assert len(room.connections) == 0
    assert len(room.votes) == 0
    assert websocket1 not in room.voterSocket
    assert websocket2 not in room.voterSocket

def test_is_expired(room):
    room.last_activity = datetime.now() - timedelta(seconds=3601)
    assert room.is_expired() is True

    room.reset_activty()
    assert room.is_expired() is False
