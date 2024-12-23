
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
        self.voters:Dict[WebSocket,str] = {}
        self.settings =Settings(reveal=self.reveal,clear=self.clear,votingCard=self.votingCard)
        self.ttl_seconds = ttl # default 4 weeks.
        self.last_activity = datetime.now()
        
    async def connect(self, websocket:WebSocket, name:str):
        self.connections.append(websocket)
        #List of names to be useful
        self.voters[websocket] = name
        self.cast_vote(name,"")
        await self.broadcast_votes()
        await self.broadcast_settings(self.settings)

    async def broadcast_votes(self):
        print("Broadcasting Votes")
        votes = {
                "type":"result",
                "roomID": self.roomID,         
                "votes":self.votes
            }
        for connection in self.connections:
            try:
                await connection.send_json(votes)
            except Exception as e:
                print(f"Failed to send vote update to {connection}: {e}")
        
    async def broadcast_settings(self,settings:Settings):
        self.reveal = settings.reveal
        self.votingCard = settings.votingCard
        for connection in self.connections:
            try:
                await connection.send_json({"type":"settings","reveal":self.reveal,"votingCard":self.votingCard})
            except Exception as e:
                print(f"Failed to send settings update to {connection}: {e}")
    
    def cast_vote(self,voter:str,vote:str)->None:
        #allows revoting
        self.votes[voter] = vote
        
    def clear_votes(self):
        for votes in self.votes:
            self.votes[votes] =""
    
    async def disconnect(self,websocket:WebSocket):
        #remove websocket from voters list
        if websocket not in self.voters and websocket not in self.connections:
            print(f"WebSocket {websocket} not found in voters or connections")
        else:
            if websocket in self.voters:
                name = self.voters.pop(websocket)
                #remove name and vote from votes list.
                if name in self.votes:
                    self.votes.pop(name)
                    print("name removed")
            #Disconnect websocket connection
            try:
                await websocket.close(code=1000, reason="User left room")
            except Exception as e:
                print(f"Failed to close WebSocket: {e}")
                
            #remove from connections list.
            if websocket in self.connections:
                self.connections.remove(websocket)
            print(f"Disconnected: {websocket} from room {self.roomID}")
            #broadcast updated votes list.
            try:
                await self.broadcast_votes()
                print("broadcast after deleted voter.")
            except Exception as e:
                print(f"Failed to broadcast votes: {e}")
            
            
            
            
            
            
            
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

