import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import ScrumpokerAPI.room_manager as room_manager_module
from ScrumpokerAPI.room_manager import RoomManager


@pytest.fixture
def manager():
    return RoomManager()


def test_get_or_create_creates_once(manager):
    room1 = manager.get_or_create("r1")
    room2 = manager.get_or_create("r1")
    assert room1 is room2
    assert "r1" in manager.rooms


def test_get_returns_none_for_missing_room(manager):
    assert manager.get("missing") is None


def test_delete_removes_room(manager):
    manager.get_or_create("r1")
    manager.delete("r1")
    assert manager.get("r1") is None


def test_delete_missing_room_is_a_noop(manager):
    manager.delete("does-not-exist")  # should not raise


def test_is_name_taken_false_when_room_does_not_exist(manager):
    assert manager.is_name_taken("no-room", "Alice") is False


def test_is_name_taken(manager):
    room = manager.get_or_create("r1")
    room.voters.append(SimpleNamespace(display_name="Alice"))

    assert manager.is_name_taken("r1", "Alice") is True
    assert manager.is_name_taken("r1", "Bob") is False


@pytest.mark.asyncio
async def test_cleanup_task_removes_only_expired_rooms(manager, monkeypatch):
    # Speed the loop up so the test doesn't actually wait a week.
    monkeypatch.setattr(room_manager_module, "CLEANUP_INTERVAL_SECONDS", 0.01)

    expired_room = manager.get_or_create("expired")
    expired_room.ttl_seconds = 0
    expired_room.last_activity = datetime.now() - timedelta(seconds=1)

    fresh_room = manager.get_or_create("fresh")
    fresh_room.ttl_seconds = 3600
    fresh_room.last_activity = datetime.now()

    manager.start_cleanup_task()
    await asyncio.sleep(0.05)  # let the loop run at least one pass
    manager.stop_cleanup_task()

    assert "expired" not in manager.rooms
    assert "fresh" in manager.rooms


@pytest.mark.asyncio
async def test_stop_cleanup_task_is_safe_if_never_started(manager):
    manager.stop_cleanup_task()  # should not raise