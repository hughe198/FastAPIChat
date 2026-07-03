from typing import Literal
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


class Settings(BaseModel):
    reveal: bool
    votingCard: str
    reactions: dict[str, list[Reaction]] = {}
    missile_used_by: set[str] = set()