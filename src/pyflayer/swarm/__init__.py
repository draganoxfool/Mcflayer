"""Multi-bot swarm: clusters, shared worlds, staggering, claims and metrics (M7).

Examples:
    >>> cluster = BotCluster("play.example.net", port=25565)
    >>> bots = cluster.spawn(10)
    >>> async with cluster:
    ...     await cluster.wait_until_ready(timeout=60)
    ...     await cluster.broadcast("hello")

See :mod:`pyflayer.swarm.cluster`, :mod:`pyflayer.swarm.shared`,
:mod:`pyflayer.swarm.stagger`, :mod:`pyflayer.swarm.coordinator` and
:mod:`pyflayer.swarm.metrics`.
"""

from __future__ import annotations

from pyflayer.swarm.cluster import (
    BotCluster,
    BotErrorEvent,
    BotKickedEvent,
    BotReconnectEvent,
    BotSpawnEvent,
)
from pyflayer.swarm.coordinator import (
    Blackboard,
    BlackboardChangedEvent,
    Claim,
    ClaimRegistry,
    PathCache,
    PathCacheStats,
    RegionClaim,
    RoleRegistry,
)
from pyflayer.swarm.metrics import BotMetrics, ClusterMetrics
from pyflayer.swarm.shared import SharedWorld, SharedWorldRegistry
from pyflayer.swarm.stagger import LoginStaggerPolicy

__all__ = [
    "Blackboard",
    "BlackboardChangedEvent",
    "BotCluster",
    "BotErrorEvent",
    "BotKickedEvent",
    "BotMetrics",
    "BotReconnectEvent",
    "BotSpawnEvent",
    "Claim",
    "ClaimRegistry",
    "ClusterMetrics",
    "LoginStaggerPolicy",
    "PathCache",
    "PathCacheStats",
    "RegionClaim",
    "RoleRegistry",
    "SharedWorld",
    "SharedWorldRegistry",
]
