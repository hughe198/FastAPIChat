from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import Dict, List, Optional
from fastapi.middleware.cors import CORSMiddleware
from room import Room, Settings, Vote
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
    await websocket.accept()
    room:Optional[Room] = None
    status = False
    message = ""
    name = ""
    try:
        data = await websocket.receive_json()
        name = data.get('name')
        if not name:
            await websocket.send_json({"type": "error", "error": "Name is required"})
            return
        print(f'Received connection from {name} for room ID {room_id}')
        if room_id not in rooms:
            rooms[room_id] = Room(room_id)
        room = rooms[room_id]
        status,message = await room.connect(websocket,name)
    except WebSocketDisconnect:
        print(f"Client disconnected from room_id: {room_id}")
         
    if room is not None and status:
        try:
            while True:
                try:     
                    data = await websocket.receive_json()
                    if "command" in data:               
                        command = data.get("command")
                        if command =="Clear_votes":
                            print("Clearing votes")
                            room.clear_votes()
                            await room.broadcast_votes()
                        elif command == "Delete_room":
                            if room_id in rooms:
                                await websocket.send_json({"type":"success","success":"Room Deleted"})
                                await room.disconnect_all()
                                rooms.pop(room_id)    
                            else:
                                await websocket.send_json({"type":"error","error":"Room doesn''t exist"})
                                print("Error: Room does not exist")
                            break
                        elif command=="Reveal_votes":
                            await room.broadcast_votes()
                            room.reveal = not room.reveal
                            settings= room.getSettings()
                            await room.broadcast_settings(settings)
                        elif command=="Exit_room":
                            await websocket.send_json({"type":"success","success":"Exiting Room"})
                            await room.disconnect(websocket)
                            break
                        else:
                            await websocket.send_json({"type":"error","error":"Unknown Command"})
                    elif "Card_Change" in data:
                        card = data.get("Card_Change")
                        room.votingCard = card
                        settings= room.getSettings()
                        await room.broadcast_settings(settings)
                            
                    elif "voter" in data and "vote" in data:
                        try:
                            vote = Vote(**data)
                            room.cast_vote(vote.voter,vote.vote)
                            await room.broadcast_votes()
                        except ValueError as e:
                            await websocket.send_json({"type":"error","error": "Invalid vote data format or missing fields", "details": str(e)})
                            print(f"Error parsing vote data: {str(e)}")
                    elif "settings" in data:
                        try:
                            settings = Settings(**data)
                            await room.broadcast_settings(settings)
                        except ValueError as e:
                            await websocket.send_json({"type":"error","error": "Invalid settings data format or missing fields", "details": str(e)})
                            print(f"Error parsing settings data: {str(e)}") 
                    else:
                        await websocket.send_json({"type":"error","error": "Invalid data format"})
                        print("Error: Received data does not match expected formats")
                except ValueError as e:
                    await websocket.send_json({"type":"error","error": "Vote parsing error", "details": str(e)})
                    print(f"Error parsing vote data: {str(e)}")

                except WebSocketDisconnect:
                     print(f"WebSocket disconnect detected: {name}")
                     await room.disconnect(websocket)
                     break

                except Exception as e:
                    print(f"Error in WebSocket loop: {e}")
                    await websocket.send_json({"type": "error", "error": str(e)})
                    break
                        
        except WebSocketDisconnect:
            if room is not None:
                await room.disconnect(websocket)
            print(f"WebSocket disconnected from room {room_id}")
        except Exception as e: 
            if room is not None:
                await room.disconnect(websocket)
            print(f"WebSocket connection error: {str(e)}")
        else:
            print(message)
            await room.disconnect(websocket)

