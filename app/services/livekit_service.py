"""LiveKit integration service for real-time voice."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from livekit import api
from livekit.api import AccessToken, VideoGrants

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class LiveKitService:
    """Service for managing LiveKit rooms and participants."""

    def __init__(self) -> None:
        self.api_key = settings.livekit_api_key
        self.api_secret = settings.livekit_api_secret
        self.url = settings.livekit_url

    def create_access_token(
        self,
        identity: str,
        room_name: str,
        grants: VideoGrants | None = None,
        ttl: timedelta = timedelta(hours=1),
    ) -> str:
        """Create a LiveKit access token for a participant."""
        if grants is None:
            grants = VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
            )

        token = AccessToken(
            api_key=self.api_key,
            api_secret=self.api_secret,
        )
        token.identity = identity
        token.name = identity
        token.video_grants = grants
        token.ttl = ttl

        return token.to_jwt()

    def create_room_token(
        self,
        room_name: str,
        participant_identity: str,
        is_agent: bool = False,
    ) -> str:
        """Create a token for joining a room."""
        grants = VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
            hidden=is_agent,  # Agents can be hidden from participant list
        )

        return self.create_access_token(
            identity=participant_identity,
            room_name=room_name,
            grants=grants,
        )

    async def create_room(
        self,
        room_name: str,
        empty_timeout: int = 300,  # 5 minutes
        max_participants: int = 10,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new LiveKit room."""
        room_service = api.RoomService(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        room = await room_service.create_room(
            api.CreateRoomRequest(
                name=room_name,
                empty_timeout=empty_timeout,
                max_participants=max_participants,
                metadata=str(metadata) if metadata else None,
            )
        )

        logger.info("LiveKit room created", room_name=room_name, room_sid=room.sid)

        return {
            "sid": room.sid,
            "name": room.name,
            "creation_time": room.creation_time,
            "max_participants": room.max_participants,
        }

    async def delete_room(self, room_name: str) -> None:
        """Delete a LiveKit room."""
        room_service = api.RoomService(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        await room_service.delete_room(api.DeleteRoomRequest(room=room_name))
        logger.info("LiveKit room deleted", room_name=room_name)

    async def list_rooms(self) -> list[dict[str, Any]]:
        """List all active rooms."""
        room_service = api.RoomService(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        response = await room_service.list_rooms(api.ListRoomsRequest())

        return [
            {
                "sid": room.sid,
                "name": room.name,
                "num_participants": room.num_participants,
                "creation_time": room.creation_time,
            }
            for room in response.rooms
        ]

    async def list_participants(self, room_name: str) -> list[dict[str, Any]]:
        """List participants in a room."""
        room_service = api.RoomService(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        response = await room_service.list_participants(
            api.ListParticipantsRequest(room=room_name)
        )

        return [
            {
                "sid": p.sid,
                "identity": p.identity,
                "name": p.name,
                "state": p.state,
                "joined_at": p.joined_at,
            }
            for p in response.participants
        ]

    async def remove_participant(self, room_name: str, identity: str) -> None:
        """Remove a participant from a room."""
        room_service = api.RoomService(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        await room_service.remove_participant(
            api.RoomParticipantIdentity(room=room_name, identity=identity)
        )
        logger.info("Participant removed", room_name=room_name, identity=identity)

    async def send_data(
        self,
        room_name: str,
        data: bytes,
        destination_identities: list[str] | None = None,
        topic: str | None = None,
    ) -> None:
        """Send data message to room participants."""
        room_service = api.RoomService(
            url=self.url,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        await room_service.send_data(
            api.SendDataRequest(
                room=room_name,
                data=data,
                destination_identities=destination_identities or [],
                topic=topic,
            )
        )

    def generate_room_name(self, tenant_id: uuid.UUID, call_id: uuid.UUID) -> str:
        """Generate a unique room name for a call."""
        return f"call_{tenant_id}_{call_id}"


def get_livekit_service() -> LiveKitService:
    """Get LiveKit service instance."""
    return LiveKitService()
