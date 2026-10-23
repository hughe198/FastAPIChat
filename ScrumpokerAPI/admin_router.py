"""Admin HTTP endpoints under /api/admin.

Everything is behind require_admin_enabled (404 when ADMIN_PASSWORD is
unset); everything except login also needs a valid Bearer token.
"""
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .admin_auth import (
    client_ip,
    create_token,
    login_limiter,
    password_matches,
    require_admin,
    require_admin_enabled,
)
from .room import Room
from .room_manager import room_manager

ROOM_CLOSED_BY_ADMIN = 4001

STARTED_AT = time.time()

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin_enabled)])


class LoginRequest(BaseModel):
    password: str


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def room_summary(room: Room) -> dict:
    timer = room.current_timer()
    return {
        "roomID": room.roomID,
        "voterCount": len(room.voters),
        "votedCount": sum(1 for v in room.voters if room.votes.get(v.id) and room.votes[v.id].vote != ""),
        "revealed": room.reveal,
        "votingCard": room.votingCard,
        "timerState": timer.state if timer else None,
        "createdAt": _ms(room.created_at),
        "lastActivity": _ms(room.last_activity),
        "expiresAt": _ms(room.expires_at()),
    }


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    ip = client_ip(request)
    if login_limiter.is_blocked(ip):
        raise HTTPException(status_code=429, detail="Too many attempts, try again in a minute")
    if not password_matches(body.password):
        login_limiter.record_failure(ip)
        raise HTTPException(status_code=401, detail="Wrong password")
    login_limiter.reset(ip)
    token, expires_at = create_token()
    return {"token": token, "expiresAt": expires_at}


@router.get("/session", dependencies=[Depends(require_admin)])
async def session():
    return {"ok": True}


@router.get("/rooms", dependencies=[Depends(require_admin)])
async def list_rooms():
    # Active = at least one person connected. Inactive rooms are empty
    # but kept until they expire (no activity for the room's TTL).
    summaries = [room_summary(r) for r in room_manager.rooms.values()]
    by_recent = lambda s: -s["lastActivity"]
    active = sorted((s for s in summaries if s["voterCount"] > 0), key=by_recent)
    inactive = sorted((s for s in summaries if s["voterCount"] == 0), key=by_recent)
    return {
        "stats": {
            "activeRooms": len(active),
            "inactiveRooms": len(inactive),
            "connectedUsers": sum(s["voterCount"] for s in active),
            "uptimeSeconds": int(time.time() - STARTED_AT),
        },
        "active": active,
        "inactive": inactive,
    }


@router.get("/rooms/{room_id}", dependencies=[Depends(require_admin)])
async def room_detail(room_id: str):
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    timer = room.current_timer()
    return {
        **room_summary(room),
        "voters": [
            {"name": v.display_name, "hasVoted": bool(room.votes.get(v.id) and room.votes[v.id].vote != "")}
            for v in room.voters
        ],
        "reactionCount": sum(len(r) for r in room.settings.reactions.values()),
        "missileFiredBy": sorted(room.missile_fired_names),
        "timer": timer.model_dump(mode="json") if timer else None,
    }


@router.delete("/rooms/{room_id}", dependencies=[Depends(require_admin)])
async def close_room(room_id: str):
    room = room_manager.get(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    await room.disconnect_all(code=ROOM_CLOSED_BY_ADMIN, reason="Room closed by an administrator")
    room_manager.delete(room_id)
    return {"closed": room_id}
