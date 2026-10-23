import pytest

from ScrumpokerAPI import room as room_module
from ScrumpokerAPI.room import Room
from ScrumpokerAPI.room_manager import RoomManager
from ScrumpokerAPI.message_handlers import handle_timer, handle_command
from test_helpers import make_ws


class FakeClock:
    """Replaces room.now_ms so tests can move time forward by hand."""
    def __init__(self, start: int = 1_000_000):
        self.ms = start

    def __call__(self) -> int:
        return self.ms

    def advance(self, seconds: float) -> None:
        self.ms += int(seconds * 1000)


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(room_module, "now_ms", fake)
    return fake


@pytest.fixture
def room():
    return Room(room_id="test_room", ttl=3600)


async def joined(room, name="Alice"):
    ws = make_ws()
    await room.connect(ws, name)
    ws.send_json.reset_mock()
    return ws


def last_settings(ws):
    return ws.send_json.await_args.args[0]


# ---------------------------------------------------------------------------
# Room timer state
# ---------------------------------------------------------------------------

def test_no_timer_by_default(room, clock):
    settings = room.get_settings()
    assert settings.timer is None
    assert settings.serverTime == clock.ms


def test_start_sets_running_timer_with_end_time(room, clock):
    assert room.start_timer(180, "Alice") is True

    timer = room.get_settings().timer
    assert timer.state == "running"
    assert timer.endsAt == clock.ms + 180_000
    assert timer.duration == 180
    assert timer.startedBy == "Alice"


@pytest.mark.parametrize("seconds", [0, 9, 3601, -5])
def test_start_rejects_out_of_range_durations(room, clock, seconds):
    assert room.start_timer(seconds, "Alice") is False
    assert room.timer is None


def test_pause_then_resume_keeps_remaining_time(room, clock):
    room.start_timer(180, "Alice")
    clock.advance(60)

    assert room.pause_timer() is True
    paused = room.get_settings().timer
    assert paused.state == "paused"
    assert paused.remainingMs == 120_000
    assert paused.endsAt is None

    clock.advance(300)  # time passing while paused doesn't count
    assert room.resume_timer() is True
    resumed = room.get_settings().timer
    assert resumed.state == "running"
    assert resumed.endsAt == clock.ms + 120_000


def test_add_extends_running_and_paused_timers(room, clock):
    room.start_timer(60, "Alice")
    room.add_timer_time(60)
    assert room.timer.endsAt == clock.ms + 120_000

    room.pause_timer()
    room.add_timer_time(30)
    assert room.timer.remainingMs == 150_000


def test_add_is_capped_at_the_maximum(room, clock):
    room.start_timer(3500, "Alice")
    room.add_timer_time(600)
    assert room.timer.endsAt == clock.ms + 3600_000


def test_actions_without_a_timer_are_ignored(room, clock):
    assert room.add_timer_time(60) is False
    assert room.pause_timer() is False
    assert room.resume_timer() is False
    assert room.stop_timer() is False


def test_stop_clears_the_timer(room, clock):
    room.start_timer(60, "Alice")
    assert room.stop_timer() is True
    assert room.get_settings().timer is None


def test_finished_timer_is_kept_briefly_then_dropped(room, clock):
    room.start_timer(60, "Alice")

    clock.advance(65)  # just past zero: still visible so clients can finish
    assert room.get_settings().timer is not None

    clock.advance(10)  # beyond the grace period
    assert room.get_settings().timer is None


def test_clear_votes_stops_the_timer(room, clock):
    room.start_timer(60, "Alice")
    room.clear_votes()
    assert room.timer is None


# ---------------------------------------------------------------------------
# handle_timer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_timer_start_broadcasts_to_everyone(room, clock):
    ws1 = await joined(room, "Alice")
    ws2 = await joined(room, "Bob")

    await handle_timer(room, ws1, {"type": "timer", "action": "start", "seconds": 180})

    for ws in (ws1, ws2):
        sent = last_settings(ws)
        assert sent["type"] == "settings"
        assert sent["timer"]["state"] == "running"
        assert sent["timer"]["startedBy"] == "Alice"
        assert sent["timer"]["endsAt"] == clock.ms + 180_000
        assert sent["serverTime"] == clock.ms


@pytest.mark.asyncio
async def test_handle_timer_invalid_duration_sends_error_only_to_sender(room, clock):
    ws1 = await joined(room, "Alice")
    ws2 = await joined(room, "Bob")

    await handle_timer(room, ws1, {"type": "timer", "action": "start", "seconds": 5})

    assert last_settings(ws1)["type"] == "error"
    ws2.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_timer_unknown_action_sends_error(room, clock):
    ws = await joined(room)
    await handle_timer(room, ws, {"type": "timer", "action": "explode"})
    assert last_settings(ws)["error"] == "Invalid timer data format or missing fields"


@pytest.mark.asyncio
async def test_handle_timer_add_defaults_to_one_minute(room, clock):
    ws = await joined(room)
    await handle_timer(room, ws, {"type": "timer", "action": "start", "seconds": 60})
    await handle_timer(room, ws, {"type": "timer", "action": "add"})
    assert last_settings(ws)["timer"]["endsAt"] == clock.ms + 120_000


@pytest.mark.asyncio
async def test_handle_timer_noop_action_does_not_broadcast(room, clock):
    ws = await joined(room)
    await handle_timer(room, ws, {"type": "timer", "action": "pause"})
    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_votes_command_broadcasts_stopped_timer(room, clock):
    ws = await joined(room)
    manager = RoomManager()
    manager.rooms["test_room"] = room
    await handle_timer(room, ws, {"type": "timer", "action": "start", "seconds": 60})

    await handle_command(room, ws, {"command": "Clear_votes"}, "test_room", manager)

    assert last_settings(ws)["timer"] is None
