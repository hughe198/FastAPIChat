from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from typing import List
import json
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://127.0.0.1:4000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"Connected: {websocket.client}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        print(f"Disconnected: {websocket.client}")

    async def broadcast(self, message: str, name: str = None):
        json_message = {"message": message}
        if name:
            json_message["name"] = name
        for connection in self.active_connections:
            await connection.send_json(json_message)

manager = ConnectionManager()

@app.get("/")
def get():
    return HTMLResponse("Websocket Chat Server")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                data_json = json.loads(data)
                message = data_json.get("message")
                name = data_json.get("name")
                if message is not None:
                    await manager.broadcast(message, name)
                else:
                    print("Invalid message format received")
            except json.JSONDecodeError:
                print("Failed to decode JSON")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast("A user has left the chat.")
