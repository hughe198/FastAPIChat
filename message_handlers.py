from typing import Any, Dict

from fastapi import WebSocket

from .models import Vote, Settings, Reaction
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
        return False

    if command == "Delete_room":
        if room_manager.get(room_id) is not None:
            await websocket.send_json({"type": "success", "success": "Room Deleted"})
            await room.disconnect_all()
            room_manager.delete(room_id)
        else:
            await websocket.send_json({"type": "error", "error": "Room doesn't exist"})
            print("Error: Room does not exist")
        return True

    if command == "Reveal_votes":
        await room.broadcast_votes()
        room.reveal = not room.reveal
        await room.broadcast_settings(room.get_settings())
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
    await room.broadcast_settings(room.get_settings())


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
        settings = Settings(**data)
        await room.broadcast_settings(settings)
    except ValueError as e:
        await websocket.send_json({
            "type": "error",
            "error": "Invalid settings data format or missing fields",
            "details": str(e),
        })
        print(f"Error parsing settings data: {str(e)}")


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
    else:
        result = room.add_reaction(reaction)

    if result:
        await room.broadcast_settings(room.get_settings())
