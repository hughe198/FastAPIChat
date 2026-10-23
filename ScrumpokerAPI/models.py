from typing import Literal, Optional
from pydantic import BaseModel


class Reaction(BaseModel):
    id: str            # uuid4, used for de-dupe on the client
    emoji: str
    from_voter: str
    to_voter: str
    kind: Literal["normal", "missile"] = "normal"


class Vote(BaseModel):
    voter: str
    vote: str


class TimerCommand(BaseModel):
    action: Literal["start", "add", "pause", "resume", "stop"]
    # Required for "start" (duration) and optional for "add" (default 60).
    seconds: Optional[int] = None


class TimerState(BaseModel):
    # Times are epoch milliseconds from the server clock; clients correct
    # for their own clock using Settings.serverTime.
    state: Literal["running", "paused"]
    endsAt: Optional[int] = None        # set while running
    remainingMs: Optional[int] = None   # set while paused
    duration: int                       # seconds, as originally started
    startedBy: str


class SettingsUpdate(BaseModel):
    # The only settings fields a client may change. Reactions and
    # missile_used_by are server-owned and never accepted from a client.
    reveal: bool
    votingCard: str


class Settings(BaseModel):
    reveal: bool
    votingCard: str
    reactions: dict[str, list[Reaction]] = {}
    # Voter ids that have already fired. On the wire only -- Room derives
    # it from Room.missile_fired_names in get_settings().
    missile_used_by: set[str] = set()
    timer: Optional[TimerState] = None
    serverTime: int = 0