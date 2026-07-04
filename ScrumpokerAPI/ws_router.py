from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .room_manager import room_manager
from .message_handlers import (
    handle_command,
    handle_card_change,
    handle_vote,
    handle_settings,
    handle_reaction,
)

router = APIRouter()

# Client -> server dispatch table, keyed on the message's "type" field.
# Replaces the old ad-hoc "does this key exist in the payload" routing
# (e.g. "reaction" in data, "Card_Change" in data), which required
# marker keys unrelated to the actual message content.
DISPATCHERS = {
    "cardChange": handle_card_change,
    "vote": handle_vote,
    "settings": handle_settings,
    "reaction": handle_reaction,
}


@router.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()

    try:
        data = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        print(f"Client disconnected or sent invalid handshake for room_id: {room_id}")
        return

    name = data.get("name")
    room = room_manager.get_or_create(room_id)

    if not name or room_manager.is_name_taken(room_id, name):
        print("New Name Needed")
        await websocket.send_json({"type": "error", "error": "New Name Needed"})
        await websocket.close(code=4000, reason="New Name Needed")
        return

    print(f"Received connection from {name} for room ID {room_id}")
    await room.connect(websocket, name)

    try:
        while True:
            try:
                data = await websocket.receive_json()
                msg_type = data.get("type")

                if msg_type == "command":
                    should_stop = await handle_command(room, websocket, data, room_id, room_manager)
                    if should_stop:
                        break
                elif msg_type in DISPATCHERS:
                    await DISPATCHERS[msg_type](room, websocket, data)
                else:
                    await websocket.send_json({"type": "error", "error": "Invalid data format"})
                    print("Error: Received data does not match expected formats")

            except ValueError as e:
                await websocket.send_json({"type": "error", "error": "Parsing error", "details": str(e)})
                print(f"Error parsing data: {str(e)}")

            except WebSocketDisconnect:
                print(f"WebSocket disconnect detected: {name}")
                await room.disconnect(websocket)
                break

            except Exception as e:
                print(f"Error in WebSocket loop: {e}")
                await websocket.send_json({"type": "error", "error": str(e)})
                break

    except WebSocketDisconnect:
        await room.disconnect(websocket)
        print(f"WebSocket disconnected from room {room_id}")
    except Exception as e:
        await room.disconnect(websocket)
        print(f"WebSocket connection error: {str(e)}")
