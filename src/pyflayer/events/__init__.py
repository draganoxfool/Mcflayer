"""Typed events: base class, catalog and the asynchronous bus.

Events are frozen dataclasses. The dispatch key is the class; the discord.py-style handler name
(``on_chat``) is derived from the class name. The bus resolves ``wait_for`` waiters synchronously,
then runs listeners as independent tasks so a slow or crashing handler cannot block dispatch.

Examples:
    >>> bus = EventBus()
    >>> bus.subscribe(ChatEvent, lambda event: None)
    Subscription(event=ChatEvent, priority=0, once=False)
"""

from __future__ import annotations

from pyflayer.events.base import Event, event_name
from pyflayer.events.bus import EventBus, Expectation, Subscription
from pyflayer.events.catalog import (
    BlockUpdateEvent,
    ChatEvent,
    ChunkLoadEvent,
    ChunkUnloadEvent,
    ConnectEvent,
    DeathEvent,
    DimensionChangeEvent,
    DisconnectEvent,
    EntityGoneEvent,
    EntityMetadataEvent,
    EntityMoveEvent,
    EntitySpawnEvent,
    ErrorEvent,
    ExperienceEvent,
    HealthEvent,
    InventoryChangedEvent,
    JoinEvent,
    KickEvent,
    LoginEvent,
    PhysicsTickEvent,
    PlayerInfoEvent,
    RespawnEvent,
    SpawnEvent,
    event_for_name,
)

__all__ = [
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
    "Event",
    "EventBus",
    "Expectation",
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
    "Subscription",
    "event_for_name",
    "event_name",
]
