from typing import Any, Dict

from fastapi import WebSocket

from .models import Vote, SettingsUpdate, Reaction, TimerCommand
from .room import Room
from .room_manager import RoomManager


async def handle_command(
    room: Room,
    websocket: WebSocket,
    data: Dict[str, Any],
    room_id: str,
    room_manager: RoomManager,
) -> bool:
    """Returns True if the websocket loop should stop after this message."""
    command = data.get("command")

    if command == "Clear_votes":
        print("Clearing votes")
        room.clear_votes()
        await room.broadcast_votes()
        # clear_votes() also resets reactions and missile_used_by, which
        # live in settings -- without this, clients keep showing stale ones.
        await room.broadcast_settings()
        return False

    if command == "Reveal_votes":
        await room.broadcast_votes()
        room.reveal = not room.reveal
        await room.broadcast_settings()
        return False

    if command == "Exit_room":
        await websocket.send_json({"type": "success", "success": "Exiting Room"})
        await room.disconnect(websocket)
        return True

    await websocket.send_json({"type": "error", "error": "Unknown Command"})
    return False


async def handle_card_change(room: Room, websocket: WebSocket, data: Dict[str, Any]) -> None:
    # NOTE: field renamed from "Card_Change" (which used the key itself
    # to carry the value) to a proper "card" field under the "cardChange"
    # message type, matching the rest of the unified protocol.
    card = data.get("card")
    room.votingCard = card
    await room.broadcast_settings()


async def handle_vote(room: Room, websocket: WebSocket, data: Dict[str, Any]) -> None:
    try:
        vote = Vote(**data)
        room.cast_vote(vote)
        await room.broadcast_votes()
    except ValueError as e:
        await websocket.send_json({
            "type": "error",
            "error": "Invalid vote data format or missing fields",
            "details": str(e),
        })
        print(f"Error parsing vote data: {str(e)}")


async def handle_settings(room: Room, websocket: WebSocket, data: Dict[str, Any]) -> None:
    try:
        update = SettingsUpdate(**data)
    except ValueError as e:
        await websocket.send_json({
            "type": "error",
            "error": "Invalid settings data format or missing fields",
            "details": str(e),
        })
        print(f"Error parsing settings data: {str(e)}")
        return
    room.reveal = update.reveal
    room.votingCard = update.votingCard
    await room.broadcast_settings()


async def handle_timer(room: Room, websocket: WebSocket, data: Dict[str, Any]) -> None:
    try:
        command = TimerCommand(**data)
    except ValueError as e:
        await websocket.send_json({
            "type": "error",
            "error": "Invalid timer data format or missing fields",
            "details": str(e),
        })
        print(f"Error parsing timer data: {str(e)}")
        return

    if command.action == "start":
        sender = next((v for v in room.voters if v.webSocket is websocket), None)
        if sender is None or command.seconds is None:
            return
        changed = room.start_timer(command.seconds, sender.display_name)
        if not changed:
            await websocket.send_json({"type": "error", "error": "Timer must be between 10 seconds and 60 minutes"})
            return
    elif command.action == "add":
        changed = room.add_timer_time(command.seconds or 60)
    elif command.action == "pause":
        changed = room.pause_timer()
    elif command.action == "resume":
        changed = room.resume_timer()
    else:
        changed = room.stop_timer()

    if changed:
        await room.broadcast_settings()


async def handle_reaction(room: Room, websocket: WebSocket, data: Dict[str, Any]) -> None:
    sender_id = room.get_sender_id(websocket)
    if sender_id is None:
        return  # sender not recognized (e.g. mid-disconnect) -- drop silently

    # The client never sends from_voter (the interface doesn't expose it,
    # and it shouldn't be trusted if it did). Inject it into the payload
    # BEFORE validation, rather than constructing the Reaction first and
    # overwriting after -- from_voter is a required field on the model,
    # so validating first would reject every legitimate reaction.
    payload = {**data, "from_voter": sender_id}

    try:
        reaction = Reaction(**payload)
    except ValueError as e:
        await websocket.send_json({
            "type": "error",
            "error": "Invalid reaction data format or missing fields",
            "details": str(e),
        })
        print(f"Error parsing reaction data: {str(e)}")
        return

    if reaction.kind == "missile":
        result = room.fire_missile(reaction)
        if result:
            await room.broadcast_missile(result)
    else:
        result = room.add_reaction(reaction)

    if result:
        await room.broadcast_settings()
