from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .room_manager import room_manager
from .ws_router import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    room_manager.start_cleanup_task()
    yield
    room_manager.stop_cleanup_task()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)


@app.get("/rooms")
async def get_active_rooms():
    room_data = {}
    for room_id, room in room_manager.rooms.items():
        room_data[room_id] = {
            "connected_users": [v.display_name for v in room.voters],
            "votes": {k: v.model_dump(mode="json") for k, v in room.votes.items()},
            "reveal": room.reveal,
            "votingCard": room.votingCard,
        }
    return JSONResponse(content=room_data)

# uvicorn main:app --port 9001