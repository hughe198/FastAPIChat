import asyncio
from typing import Dict, Optional

from .room import Room

CLEANUP_INTERVAL_SECONDS = 604_800  # 1 week


class RoomManager:
    """Owns the registry of active rooms and the background expiry task.

    Kept separate from the websocket handler so room lifecycle (create,
    fetch, delete, name-collision checks) can be tested and reasoned about
    without spinning up a real websocket connection.
    """

    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    def get_or_create(self, room_id: str) -> Room:
        if room_id not in self.rooms:
            self.rooms[room_id] = Room(room_id)
        return self.rooms[room_id]

    def get(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id)

    def delete(self, room_id: str) -> None:
        self.rooms.pop(room_id, None)

    def is_name_taken(self, room_id: str, name: str) -> bool:
        room = self.rooms.get(room_id)
        if room is None:
            return False
        # Bug fix: previously compared `name in room.voters`, which checks
        # a string against a list of Voter objects and never matched.
        return name in (v.display_name for v in room.voters)

    def start_cleanup_task(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_rooms())

    def stop_cleanup_task(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()

    async def _cleanup_expired_rooms(self) -> None:
        while True:
            print("Cleanup Task started")
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            for room_id in list(self.rooms.keys()):
                room = self.rooms[room_id]
                if room.is_expired():
                    await room.disconnect_all()
                    del self.rooms[room_id]
                    print(f"Room {room_id} has been deleted due to inactivity.")


room_manager = RoomManager()