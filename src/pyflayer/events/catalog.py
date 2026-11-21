"""Public event catalog.

Every event is a frozen, slotted dataclass. Handler names are derived from the class name, so
``ChatEvent`` is delivered to ``async def on_chat(event)``.

Examples:
    >>> from pyflayer.events import event_for_name
    >>> event_for_name("on_chat").__name__
    'ChatEvent'
"""

from __future__ import annotations

from dataclasses import dataclass

from pyflayer.events.base import Event
from pyflayer.models.chat import ChatMessage
from pyflayer.models.text import ChatComponent
from pyflayer.models.vec3 import Vec3

__all__ = [
    "EVENT_CATALOG",
    "BlockUpdateEvent",
    "ChatEvent",
    "ChunkLoadEvent",
    "ChunkUnloadEvent",
    "ConnectEvent",
    "DeathEvent",
    "DimensionChangeEvent",
    "DisconnectEvent",
    "EntityGoneEvent",
    "EntityMetadataEvent",
    "EntityMoveEvent",
    "EntitySpawnEvent",
    "ErrorEvent",
    "ExperienceEvent",
    "HealthEvent",
    "InventoryChangedEvent",
    "JoinEvent",
    "KickEvent",
    "LoginEvent",
    "PhysicsTickEvent",
    "PlayerInfoEvent",
    "RespawnEvent",
    "SpawnEvent",
    "event_for_name",
]


@dataclass(frozen=True, slots=True)
class ConnectEvent(Event):
    """TCP connect and login handshake started."""

    host: str
    port: int
    protocol: int


@dataclass(frozen=True, slots=True)
class LoginEvent(Event):
    """Login Success received; the connection is entering Play."""

    username: str
    uuid: str


@dataclass(frozen=True, slots=True)
class JoinEvent(Event):
    """Join Game (1.8 ``login``) received."""

    entity_id: int
    game_mode: int
    dimension: int
    difficulty: int
    max_players: int
    level_type: str


@dataclass(frozen=True, slots=True)
class SpawnEvent(Event):
    """The server sent the player's position; the bot is now spawned."""

    position: Vec3
    yaw: float = 0.0
    pitch: float = 0.0


@dataclass(frozen=True, slots=True)
class RespawnEvent(Event):
    """Respawn packet received from the server."""

    dimension: int


@dataclass(frozen=True, slots=True)
class DeathEvent(Event):
    """Health reached zero."""

    health: float


@dataclass(frozen=True, slots=True)
class HealthEvent(Event):
    """Health/food changed."""

    health: float
    food: int
    saturation: float


@dataclass(frozen=True, slots=True)
class ChatEvent(Event):
    """A chat line (public chat, system message or action bar)."""

    message: ChatMessage


@dataclass(frozen=True, slots=True)
class PlayerInfoEvent(Event):
    """A player-info entry was added, updated or removed."""

    action: str
    uuid: str
    name: str | None = None
    ping: int | None = None
    game_mode: int | None = None
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class KickEvent(Event):
    """The server disconnected the bot with a reason component."""

    reason: ChatComponent
    reason_text: str


@dataclass(frozen=True, slots=True)
class DisconnectEvent(Event):
    """The connection ended (clean close, kick or network error)."""

    reason: str
    error: BaseException | None = None


@dataclass(frozen=True, slots=True)
class ErrorEvent(Event):
    """A listener or ``wait_for`` check raised."""

    event: object
    listener: object
    exception: BaseException


@dataclass(frozen=True, slots=True)
class ChunkLoadEvent(Event):
    """A chunk column was decoded and inserted into the world."""

    pos: object
    sections: int = 0
    non_air: int = 0


@dataclass(frozen=True, slots=True)
class ChunkUnloadEvent(Event):
    """A chunk column was removed."""

    pos: object


@dataclass(frozen=True, slots=True)
class BlockUpdateEvent(Event):
    """A single block changed (state ids are 1.8 ``(id << 4) | meta``)."""

    pos: object
    state_id: int
    old_state_id: int


@dataclass(frozen=True, slots=True)
class EntitySpawnEvent(Event):
    """An entity or player spawned."""

    entity: object


@dataclass(frozen=True, slots=True)
class EntityMoveEvent(Event):
    """An entity moved (relative packet, teleport or velocity)."""

    entity: object
    old_position: object | None = None


@dataclass(frozen=True, slots=True)
class EntityGoneEvent(Event):
    """An entity was removed from tracking."""

    entity: object


@dataclass(frozen=True, slots=True)
class EntityMetadataEvent(Event):
    """Entity metadata was updated."""

    entity_id: int
    metadata: object


@dataclass(frozen=True, slots=True)
class InventoryChangedEvent(Event):
    """A window slot changed."""

    window_id: int
    slot: int
    item: object


@dataclass(frozen=True, slots=True)
class DimensionChangeEvent(Event):
    """The bot switched dimension on respawn."""

    dimension: int
    previous: int | None = None


@dataclass(frozen=True, slots=True)
class ExperienceEvent(Event):
    """Experience bar/level updated."""

    bar: float
    level: int
    total: int


@dataclass(frozen=True, slots=True)
class PhysicsTickEvent(Event):
    """One completed physics tick."""

    tick: int
    position: Vec3
    on_ground: bool


EVENT_CATALOG: dict[str, type] = {
    cls.__event_name__: cls
    for cls in (
        ConnectEvent,
        LoginEvent,
        JoinEvent,
        SpawnEvent,
        RespawnEvent,
        DeathEvent,
        HealthEvent,
        ChatEvent,
        PlayerInfoEvent,
        KickEvent,
        DisconnectEvent,
        ErrorEvent,
        ChunkLoadEvent,
        ChunkUnloadEvent,
        BlockUpdateEvent,
        EntitySpawnEvent,
        EntityMoveEvent,
        EntityGoneEvent,
        EntityMetadataEvent,
        InventoryChangedEvent,
        DimensionChangeEvent,
        ExperienceEvent,
        PhysicsTickEvent,
    )
}


def event_for_name(name: str) -> type:
    """Resolve ``on_chat`` to ``ChatEvent``.

    Raises:
        KeyError: When no event has that handler name.
    """
    return EVENT_CATALOG[name]
