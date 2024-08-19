from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Dict, List
from fastapi.middleware.cors import CORSMiddleware
from lobby import Room, Vote
import asyncio
app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://127.0.0.1:4000",
    "http://127.0.0.1:8000",
    "ws://127.0.0.1:8000/",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
rooms: Dict[str,Room] ={} #{room_id:Rooms}

@asynccontextmanager
async def lifespan(app:FastAPI):
    cleanup_task = asyncio.create_task(cleanup_expired_rooms())
    yield # code before yield is run during startup, 
    cleanup_task.cancel()
    
app.router.lifespan_context = lifespan

async def cleanup_expired_rooms():
    while True:
        print("Cleanup Task started")
        await asyncio.sleep(604_800) # repeat every 2 weeks
        for room_id in list(rooms.keys()):
            room = rooms[room_id]
            if room.is_expired():
                await room.disconnect_all()
                del rooms[room_id]
                print(f'Room {room_id} has beed deleted due to inactivity.')

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket,room_id:str):
    if room_id not in rooms:
        rooms[room_id] = Room(room_id)
    room:Room = rooms[room_id]
    await room.connect(websocket)
    await websocket.send_text("New Connection accepted.")
    try:
        while True:
            try:     
                data = await websocket.receive_json()
                
                if data.get("command") =="Clear_votes":
                    room.clear_votes()
                    await room.broadcast_votes()
                elif data.get("command") == "Delete_room":
                    if room_id in rooms:
                        await room.disconnect_all()
                        rooms.pop(room_id)    
                    else:
                        await websocket.send_json({"error":"Room does not exist"})
                    break
                elif data.get("command")=="Exit_room":
                    await room.disconnect(websocket)
                    break
                else:
                    vote = Vote(**data)
                    room.cast_vote(vote.voter,vote.vote)
                    await room.broadcast_votes()
                    
            except ValueError as e:
                print(f"Error parsing vote data: {str(e)}")
                await websocket.send_json({"error": "Invalid vote data format or missing fields"})

            except Exception as e:
                print(f"Error: {str(e)}")
                await websocket.send_json({"error": "An unexpected error occurred"})
                break
    except WebSocketDisconnect:
        room.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket connection error: {str(e)}")
        room.disconnect(websocket)

