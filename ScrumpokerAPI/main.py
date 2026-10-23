from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .admin_router import router as admin_router
from .config import config
from .room_manager import room_manager
from .ws_router import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    room_manager.start_cleanup_task()
    yield
    room_manager.stop_cleanup_task()


app = FastAPI(lifespan=lifespan)

# No cookies are used (admin auth is a Bearer header), so credentials stay
# off -- which is also what makes allow_origins=["*"] valid.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
# The old public GET /rooms (every room id, name and unrevealed vote, with
# no auth) is replaced by the authenticated /api/admin/rooms.
app.include_router(admin_router)

# uvicorn ScrumpokerAPI.main:app --port 9001
