
from datetime import datetime
from typing import Dict, List
from fastapi import WebSocket
from pydantic import BaseModel

class Vote(BaseModel):
    voter: str
    vote:str

class Settings(BaseModel):
    reveal: bool
    votingCard: str

class Room():
    def __init__(self,roomID:str, ttl: int = 2_419_200) -> None:
        self.reveal = False
        self.clear = False
        self.votingCard = "Fibonacci"
        self.roomID = roomID
        self.votes: Dict[str,str] = {}
        self.connections:List[WebSocket] = []
        self.ttl_seconds = ttl # default 4 weeks.
        self.last_activity = datetime.now()
        self.voters =[]
        self.settings =Settings(reveal=self.reveal,clear=self.clear,votingCard=self.votingCard)
        
    async def connect(self, websocket:WebSocket):
        await websocket.accept()
        self.connections.append(websocket)
        await self.broadcast_votes()
        await self.broadcast_settings(self.settings)

    async def broadcast_votes(self):
        print("Broadcasting Votes")
        for connection in self.connections:
            votes = {
                "type":"result",
                "roomID": self.roomID,         
                "votes":self.votes
            }
            await connection.send_json(votes)
        
    async def broadcast_settings(self,settings:Settings):
        self.reveal = settings.reveal
        self.votingCard = settings.votingCard
        for connection in self.connections:
            await connection.send_json({"type":"settings","reveal":self.reveal,"votingCard":self.votingCard})
            
    def get_voters(self):
        self.voters.clear()
        self.voters = list(self.votes.keys())
    
    def cast_vote(self,voter:str,vote:str)->None:
        #allows revoting
        self.votes[voter] = vote
        
    def clear_votes(self):
        for votes in self.votes:
            self.votes[votes] =""
    
    async def disconnect(self,websocket:WebSocket):
        if websocket in self.connections:
            self.connections.remove(websocket)
            await websocket.close(code = 1000, reason = "User left room")
            print(f"Disconnected: {websocket} from room {self.roomID}")
            self.broadcast_votes()
        else:
            print(f"Attempted to disconnect a websocket that was not in the list: {websocket}")

    async def disconnect_all(self):
        for connection in self.connections[:]:  # Use a copy of the list
            try:
                await connection.close(code=1000, reason="Room is being deleted")
            except Exception as e:
                print(f"Error disconnecting {connection}: {str(e)}")
        self.connections.clear()  # Clear the list after all connections are closed
    def reset_activty(self):
        self.last_activity = datetime.now()
            
    def is_expired(self):
        return datetime.now() > self.last_activity + datetime.timedelta(seconds = self.ttl_seconds)


    def getSettings(self):
        settings:Settings =Settings(reveal=self.reveal,clear=self.clear,votingCard=self.votingCard)
        return settings

