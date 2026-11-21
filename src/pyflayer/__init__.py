"""PyFlayer: asyncio Minecraft Java Edition bot library.

M1-M3 provide transport, login, events, a bot and world state; M4 adds deterministic physics, a
20 TPS driver, movement packets and teleport reconciliation. The reference target is
**Minecraft 1.8.9 (protocol 47)**;
version-specific behaviour is feature-gated so newer versions can be added with data, not package
rewrites. See ``docs/sessions.md`` and ``docs/tasks.md``.

Examples:
    >>> import pyflayer
    >>> pyflayer.McData.load("1.8.9").version.protocol
    47
"""

from __future__ import annotations

from pyflayer import errors
from pyflayer.bot import Bot
from pyflayer.data import Features, McData, VersionInfo
from pyflayer.errors import PyFlayerError
from pyflayer.events import ChatEvent, EventBus, JoinEvent, SpawnEvent
from pyflayer.models import (
    AABB,
    BlockPos,
    ChatComponent,
    ChatMessage,
    ChunkPos,
    Dimension,
    GameMode,
    ItemStack,
    SectionPos,
    Vec3,
)
from pyflayer.physics import ControlState, PhysicsEngine, PlayerState, TickDriver
from pyflayer.protocol import (
    Connection,
    ConnectionState,
    FrameCodec,
    Packet,
    PacketReader,
    PacketRegistry,
    PacketWriter,
    ProtocolClient,
    StateMachine,
)
from pyflayer.world import (
    BlockState,
    ChunkColumn,
    ChunkSection,
    Entity,
    EntityTracker,
    PalettedContainer,
    RayHit,
    World,
    WorldSnapshot,
)

__version__ = "0.8.0"
PROTOCOL_VERSION = 47
REFERENCE_VERSION = "1.8.9"

__all__ = [
    "AABB",
    "PROTOCOL_VERSION",
    "REFERENCE_VERSION",
    "BlockPos",
    "BlockState",
    "Bot",
    "ChatComponent",
    "ChatEvent",
    "ChatMessage",
    "ChunkColumn",
    "ChunkPos",
    "ChunkSection",
    "Connection",
    "ConnectionState",
    "ControlState",
    "Dimension",
    "Entity",
    "EntityTracker",
    "EventBus",
    "Features",
    "FrameCodec",
    "GameMode",
    "ItemStack",
    "JoinEvent",
    "McData",
    "Packet",
    "PacketReader",
    "PacketRegistry",
    "PacketWriter",
    "PalettedContainer",
    "PhysicsEngine",
    "PlayerState",
    "ProtocolClient",
    "PyFlayerError",
    "RayHit",
    "SectionPos",
    "ServerStatus",
    "SpawnEvent",
    "StateMachine",
    "TickDriver",
    "Vec3",
    "VersionInfo",
    "World",
    "WorldSnapshot",
    "__version__",
    "errors",
    "ping",
]


def __getattr__(name: str) -> object:
    # Server List Ping types are loaded lazily; see pyflayer.protocol.__getattr__.
    if name in {"ServerStatus", "ping"}:
        from pyflayer.protocol import status

        return getattr(status, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
