
from datetime import datetime
from typing import Dict, List
from fastapi import WebSocket
from pydantic import BaseModel

class Vote(BaseModel):
    voter: str
    vote:str



class Room():
    def __init__(self,roomID:str, ttl: int = 2_419_200) -> None:
        self.roomID = roomID
        self.votes: Dict[str,str] = {}
        self.connections:List[WebSocket] = []
        self.ttl_seconds = ttl # default 4 weeks.
        self.last_activity = datetime.now()
        
    async def connect(self, websocket:WebSocket):
        await websocket.accept()
        self.connections.append(websocket)
        await self.broadcast_votes()
    
    def disconnect(self,websocket:WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)
            print(f"Disconnected: {websocket} from room {self.roomID}")
        else:
            print(f"Attempted to disconnect a websocket that was not in the list: {websocket}")

    
    async def broadcast_votes(self):
        for connection in self.connections:
            votes = {
                "roomID": self.roomID,
                "votes":self.votes                
            }
            await connection.send_json(votes)
    
    def cast_vote(self,voter:str,vote:str)->None:
        #allows revoting
        self.votes[voter] = vote
        
    def clear_votes(self):
        self.votes.clear()
    
    async def disconnect_all(self):
        for connection in self.connections[:]:  # Use a copy of the list
            try:
                await connection.send_text("Room Closing...")
                await connection.close(code=1000, reason="Room is being deleted")
            except Exception as e:
                print(f"Error disconnecting {connection}: {str(e)}")
        self.connections.clear()  # Clear the list after all connections are closed
            
    def reset_activty(self):
        self.last_activity = datetime.now()
            
    def is_expired(self):
        return datetime.now() > self.last_activity + datetime.timedelta(seconds = self.ttl_seconds)
    