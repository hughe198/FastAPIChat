from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from ScrumpokerAPI import admin_auth
from ScrumpokerAPI.admin_auth import create_token, verify_token, LoginRateLimiter
from ScrumpokerAPI.config import config
from ScrumpokerAPI.main import app
from ScrumpokerAPI.models import Vote
from ScrumpokerAPI.room import Room
from ScrumpokerAPI.room_manager import room_manager

PASSWORD = "correct horse"


@pytest.fixture(autouse=True)
def admin_setup(monkeypatch):
    monkeypatch.setattr(config, "admin_password", PASSWORD)
    monkeypatch.setattr(config, "admin_secret", "test-secret")
    monkeypatch.setattr(config, "admin_token_hours", 8)
    monkeypatch.setattr(admin_auth, "login_limiter", LoginRateLimiter())
    # admin_router imported login_limiter by name, so patch it there too.
    from ScrumpokerAPI import admin_router
    monkeypatch.setattr(admin_router, "login_limiter", admin_auth.login_limiter)
    room_manager.rooms.clear()
    yield
    room_manager.rooms.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def auth_headers(client) -> dict:
    token = client.post("/api/admin/login", json={"password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def fake_voter(voter_id: str, name: str):
    return SimpleNamespace(id=voter_id, display_name=name, webSocket=SimpleNamespace(close=AsyncMock()))


def add_room(room_id: str, voters=(), votes=None, last_active_minutes_ago=0) -> Room:
    room = Room(room_id)
    for voter_id, name in voters:
        room.voters.append(fake_voter(voter_id, name))
        room.votes[voter_id] = Vote(voter=voter_id, vote=(votes or {}).get(voter_id, ""))
    room.last_activity = datetime.now() - timedelta(minutes=last_active_minutes_ago)
    room_manager.rooms[room_id] = room
    return room


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def test_token_round_trip():
    token, expires_at = create_token(now=1000)
    assert verify_token(token, now=1001) is True
    assert expires_at == (1000 + 8 * 3600) * 1000


def test_expired_token_is_rejected():
    token, _ = create_token(now=1000)
    assert verify_token(token, now=1000 + 8 * 3600 + 1) is False


@pytest.mark.parametrize("bad", ["", "nonsense", "abc.def", "a.b.c"])
def test_malformed_tokens_are_rejected(bad):
    assert verify_token(bad) is False


def test_tampered_token_is_rejected():
    token, _ = create_token()
    payload, signature = token.split(".")
    assert verify_token(f"{payload}x.{signature}") is False


def test_token_signed_with_another_secret_is_rejected(monkeypatch):
    token, _ = create_token()
    monkeypatch.setattr(config, "admin_secret", "different")
    assert verify_token(token) is False


# ---------------------------------------------------------------------------
# Login and access control
# ---------------------------------------------------------------------------

def test_login_with_correct_password_returns_token(client):
    response = client.post("/api/admin/login", json={"password": PASSWORD})
    assert response.status_code == 200
    assert verify_token(response.json()["token"])


def test_login_with_wrong_password_is_401(client):
    response = client.post("/api/admin/login", json={"password": "nope"})
    assert response.status_code == 401


def test_login_is_rate_limited_after_five_failures(client):
    for _ in range(5):
        client.post("/api/admin/login", json={"password": "nope"})
    response = client.post("/api/admin/login", json={"password": PASSWORD})
    assert response.status_code == 429


def test_rate_limit_window_expires():
    limiter = LoginRateLimiter()
    for _ in range(5):
        limiter.record_failure("1.2.3.4", now=100)
    assert limiter.is_blocked("1.2.3.4", now=130) is True
    assert limiter.is_blocked("1.2.3.4", now=161) is False


@pytest.mark.parametrize("path", ["/api/admin/session", "/api/admin/rooms", "/api/admin/rooms/x"])
def test_protected_endpoints_need_a_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer junk"}).status_code == 401


def test_session_is_ok_with_a_valid_token(client):
    assert client.get("/api/admin/session", headers=auth_headers(client)).json() == {"ok": True}


def test_admin_is_disabled_without_a_password(client, monkeypatch):
    monkeypatch.setattr(config, "admin_password", "")
    assert client.post("/api/admin/login", json={"password": ""}).status_code == 404
    assert client.get("/api/admin/rooms").status_code == 404


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------

def test_rooms_are_split_into_active_and_inactive(client):
    add_room("busy", voters=[("a", "Alice"), ("b", "Bob")], votes={"a": "5"}, last_active_minutes_ago=1)
    add_room("quiet", voters=[("c", "Carol")], last_active_minutes_ago=5)
    add_room("empty", last_active_minutes_ago=60)

    data = client.get("/api/admin/rooms", headers=auth_headers(client)).json()

    assert [r["roomID"] for r in data["active"]] == ["busy", "quiet"]  # most recent first
    assert [r["roomID"] for r in data["inactive"]] == ["empty"]
    assert data["stats"]["activeRooms"] == 2
    assert data["stats"]["inactiveRooms"] == 1
    assert data["stats"]["connectedUsers"] == 3
    busy = data["active"][0]
    assert busy["voterCount"] == 2
    assert busy["votedCount"] == 1


def test_room_list_never_includes_names_or_votes(client):
    add_room("busy", voters=[("a", "Alice")], votes={"a": "13"})
    data = client.get("/api/admin/rooms", headers=auth_headers(client)).json()
    assert "Alice" not in str(data)
    assert set(data["active"][0]) == {
        "roomID", "voterCount", "votedCount", "revealed", "votingCard",
        "timerState", "createdAt", "lastActivity", "expiresAt",
    }


def test_room_detail_lists_names_and_who_voted_but_not_vote_values(client):
    room = add_room("busy", voters=[("a", "Alice"), ("b", "Bob")], votes={"a": "13"})
    room.missile_fired_names.add("Alice")

    data = client.get("/api/admin/rooms/busy", headers=auth_headers(client)).json()

    assert data["voters"] == [{"name": "Alice", "hasVoted": True}, {"name": "Bob", "hasVoted": False}]
    assert data["missileFiredBy"] == ["Alice"]
    assert all(set(v) == {"name", "hasVoted"} for v in data["voters"])  # no vote values


def test_room_detail_unknown_room_is_404(client):
    assert client.get("/api/admin/rooms/nope", headers=auth_headers(client)).status_code == 404


def test_close_room_disconnects_everyone_with_admin_code_and_deletes_it(client):
    room = add_room("busy", voters=[("a", "Alice"), ("b", "Bob")])
    sockets = [v.webSocket for v in room.voters]

    response = client.delete("/api/admin/rooms/busy", headers=auth_headers(client))

    assert response.status_code == 200
    assert room_manager.get("busy") is None
    for ws in sockets:
        ws.close.assert_awaited_once_with(code=4001, reason="Room closed by an administrator")


def test_close_unknown_room_is_404(client):
    assert client.delete("/api/admin/rooms/nope", headers=auth_headers(client)).status_code == 404
