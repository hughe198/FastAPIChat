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
        # Display names that have fired their one missile in this room.
        # Keyed by name, not voter id, so leaving and rejoining under the
        # same name doesn't grant a fresh missile. Never reset by
        # clear_votes -- it lasts for the life of the room. Deliberately
        # light enforcement: joining under a new name gets around it.
        self.missile_fired_names: set[str] = set()

    async def connect(self, websocket: WebSocket, display_name: str) -> str:
        voter = Voter(display_name=display_name, websocket=websocket)
        vote = Vote(voter=voter.id, vote="")
        self.voters.append(voter)
        self.cast_vote(vote)
        print(voter.display_name, voter.id)

        # Tell the connecting client its own server-assigned id, sent
        # directly to this one connection (not broadcast). The frontend
        # has no other way to learn which UUID is "itself" -- votes and
        # reactions are keyed by id, not display name, and nothing else
        # on the wire carries that mapping back to the client.
        try:
            await websocket.send_json({"type": "joined", "voterID": voter.id})
        except Exception as e:
            print(f"Failed to send joined message to {voter.display_name}: {e}")

        await self.broadcast_votes()
        await self.broadcast_settings()
        return voter.id

    async def broadcast_votes(self):
        print("Broadcasting Votes")
        voter_names = {v.id: v.display_name for v in self.voters}
        votes_payload = {}
        for voter_id, vote in self.votes.items():
            vote_data = vote.model_dump(mode="json")
            # displayName is looked up live rather than stored on Vote --
            # it's a property of the Voter, and this way it can never go
            # stale relative to whatever name the voter actually joined
            # with, without needing to duplicate it into stored state.
            vote_data["displayName"] = voter_names.get(voter_id, "")
            votes_payload[voter_id] = vote_data

        votes = {
            "type": "result",
            "roomID": self.roomID,
            "votes": votes_payload
        }
        for voter in self.voters:
            try:
                await voter.webSocket.send_json(votes)
            except Exception as e:
                print(f"Failed to send vote update to {voter.display_name}: {e}")
        print("broadcast votes")

    async def broadcast_settings(self):
        # Always serialises the room's own state. Callers mutate the room
        # first, then broadcast -- a client-supplied Settings object is
        # never sent out as-is, since it would carry empty reactions.
        payload = {"type": "settings", **self.get_settings().model_dump(mode="json")}

        for voter in self.voters:
            try:
                await voter.webSocket.send_json(payload)
            except Exception as e:
                print(f"Failed to send settings update to {voter.display_name}: {e}")
        print("broadcast settings")

    async def broadcast_missile(self, missile: Reaction):
        # One-off event so every client can play the launch animation and
        # sound. Sent before the settings broadcast that carries the 💥
        # chip, so clients know the chip belongs to a missile still in flight.
        voter_names = {v.id: v.display_name for v in self.voters}
        payload = {
            "type": "missile",
            "reactionID": missile.id,
            "fromVoter": missile.from_voter,
            "toVoter": missile.to_voter,
            "fromName": voter_names.get(missile.from_voter, ""),
            "toName": voter_names.get(missile.to_voter, ""),
        }
        for voter in self.voters:
            try:
                await voter.webSocket.send_json(payload)
            except Exception as e:
                print(f"Failed to send missile event to {voter.display_name}: {e}")

    def cast_vote(self, vote: Vote) -> None:
        # allows revoting
        self.votes[vote.voter] = vote

    def clear_votes(self):
        for vote in self.votes.values():
            vote.vote = ""
        # Missile use is NOT reset here -- it's once per room, see
        # missile_fired_names.
        self.settings.reactions = {}
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
                await self.broadcast_settings()
                print("Broadcast after deleted voter.")
            except Exception as e:
                print(f"Failed to broadcast after disconnect: {e}")

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

    def missile_used_ids(self) -> set[str]:
        # Clients identify themselves by voter id, so translate the stored
        # names into the ids of whoever is currently connected under them.
        return {v.id for v in self.voters if v.display_name in self.missile_fired_names}

    def get_settings(self) -> Settings:
        return Settings(
            reveal=self.reveal,
            votingCard=self.votingCard,
            missile_used_by=self.missile_used_ids(),
            reactions=self.settings.reactions,
        )

    def add_reaction(self, reaction: Reaction) -> Optional[Reaction]:
        to_voter = next((v for v in self.voters if v.id == reaction.to_voter), None)
        if not to_voter:
            return None
        existing = self.settings.reactions.get(reaction.to_voter, [])
        if any(r.from_voter == reaction.from_voter and r.emoji == reaction.emoji for r in existing):
            return None  # same sender, same emoji, same target: ignore repeat clicks
        reaction.id = str(uuid.uuid4())  # never trust a client-supplied id
        self.settings.reactions.setdefault(reaction.to_voter, []).append(reaction)
        self.last_activity = datetime.now()
        return reaction

    def fire_missile(self, reaction: Reaction) -> Optional[Reaction]:
        sender = next((v for v in self.voters if v.id == reaction.from_voter), None)
        if sender is None or sender.display_name in self.missile_fired_names:
            return None
        if not any(v.id == reaction.to_voter for v in self.voters):
            return None

        self.missile_fired_names.add(sender.display_name)
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
