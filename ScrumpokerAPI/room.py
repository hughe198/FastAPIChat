import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from .models import Vote, Settings, Reaction


class Voter:
    def __init__(self, display_name: str, websocket: WebSocket):
        self.id: str = str(uuid.uuid4())
        self.display_name: str = display_name
        self.webSocket: WebSocket = websocket


class Room:
    def __init__(self, room_id: str, ttl: int = 2_419_200) -> None:
        self.reveal = False
        self.clear = False
        self.votingCard = "Standard"
        self.roomID = room_id
        self.votes: Dict[str, Vote] = {}
        self.voters: List[Voter] = []
        self.settings = Settings(reveal=self.reveal, votingCard=self.votingCard)
        self.ttl_seconds = ttl  # default 4 weeks.
        self.last_activity = datetime.now()

    async def connect(self, websocket: WebSocket, display_name: str) -> None:
        voter = Voter(display_name=display_name, websocket=websocket)
        vote = Vote(voter=voter.id, vote="")
        self.voters.append(voter)
        self.cast_vote(vote)
        print(voter.display_name, voter.id)
        await self.broadcast_votes()
        await self.broadcast_settings(self.settings)

    async def broadcast_votes(self):
        print("Broadcasting Votes")
        votes = {
            "type": "result",
            "roomID": self.roomID,
            "votes": {str(k): v.model_dump(mode="json") for k, v in self.votes.items()}
        }
        for voter in self.voters:
            try:
                await voter.webSocket.send_json(votes)
            except Exception as e:
                print(f"Failed to send vote update to {voter.display_name}: {e}")
        print("broadcast votes")

    async def broadcast_settings(self, settings: Settings):
        self.reveal = settings.reveal
        self.votingCard = settings.votingCard
        settings_data = settings.model_dump(mode="json")
        payload = {
            "type": "settings",
            "reveal": self.reveal,
            "votingCard": self.votingCard,
            "reactions": settings_data.get("reactions", {}),
            "missile_used_by": settings_data.get("missile_used_by", [])
        }

        for voter in self.voters:
            try:
                await voter.webSocket.send_json(payload)
            except Exception as e:
                print(f"Failed to send settings update to {voter.display_name}: {e}")
        print("broadcast settings")

    def cast_vote(self, vote: Vote) -> None:
        # allows revoting
        self.votes[vote.voter] = vote

    def clear_votes(self):
        for vote in self.votes.values():
            vote.vote = ""
        self.settings.reactions = {}
        self.settings.missile_used_by = set()
        self.last_activity = datetime.now()

    async def disconnect(self, websocket: WebSocket):
        voter = next((v for v in self.voters if v.webSocket is websocket), None)

        if voter:
            try:
                if voter.webSocket.client_state == WebSocketState.CONNECTED:
                    await websocket.close(code=1000, reason=f"{voter.display_name} left room")
            except Exception as e:
                print(f"Failed to close WebSocket: {e}")

            self.voters.remove(voter)
            self.votes.pop(voter.id, None)
            self.settings.reactions.pop(voter.id, None)

            try:
                await self.broadcast_votes()
                print("Broadcast after deleted voter.")
            except Exception as e:
                print(f"Failed to broadcast votes: {e}")

    async def disconnect_all(self):
        for voter in list(self.voters):
            try:
                await voter.webSocket.close(code=1000, reason="Room is being deleted")
            except Exception as e:
                print(f"Error disconnecting {voter.display_name}: {str(e)}")

    def reset_activity(self):
        self.last_activity = datetime.now()

    def is_expired(self):
        return datetime.now() > self.last_activity + timedelta(seconds=self.ttl_seconds)

    def get_settings(self) -> Settings:
        return Settings(
            reveal=self.reveal,
            votingCard=self.votingCard,
            missile_used_by=self.settings.missile_used_by,
            reactions=self.settings.reactions,
        )

    def add_reaction(self, reaction: Reaction) -> Optional[Reaction]:
        to_voter = next((v for v in self.voters if v.id == reaction.to_voter), None)
        if not to_voter:
            return None
        reaction.id = str(uuid.uuid4())  # never trust a client-supplied id
        self.settings.reactions.setdefault(reaction.to_voter, []).append(reaction)
        self.last_activity = datetime.now()
        return reaction

    def fire_missile(self, reaction: Reaction) -> Optional[Reaction]:
        if reaction.from_voter in self.settings.missile_used_by:
            return None
        if not any(v.id == reaction.to_voter for v in self.voters):
            return None

        self.settings.missile_used_by.add(reaction.from_voter)
        missile_reaction = Reaction(
            id=str(uuid.uuid4()),
            emoji="\U0001F4A5",
            from_voter=reaction.from_voter,
            to_voter=reaction.to_voter,
            kind="missile",
        )
        self.settings.reactions.setdefault(missile_reaction.to_voter, []).append(missile_reaction)
        self.last_activity = datetime.now()
        return missile_reaction

    def get_sender_id(self, websocket: WebSocket) -> Optional[str]:
        return next((v.id for v in self.voters if v.webSocket is websocket), None)