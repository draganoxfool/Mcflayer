"""Cluster and per-bot metrics.

:meth:`BotCluster.metrics` returns a :class:`ClusterMetrics` snapshot that can be logged as a dict
or scraped as Prometheus text. Nothing here samples on its own; the cluster updates the tick
timings that the snapshot reads.

Examples:
    >>> metrics = cluster.metrics()
    >>> metrics.connected
    3
    >>> print(metrics.to_prometheus())
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["BotMetrics", "ClusterMetrics", "percentile"]


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; ``0.0`` for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


@dataclass(frozen=True, slots=True)
class BotMetrics:
    """One bot's contribution to a cluster snapshot."""

    name: str
    username: str
    connected: bool
    spawned: bool
    dead: bool
    health: float
    food: int
    dimension: int | None
    position: tuple[float, float, float] | None
    tick_group: int
    role: str | None = None


@dataclass(frozen=True, slots=True)
class ClusterMetrics:
    """Point-in-time cluster health and resource usage."""

    bots: tuple[BotMetrics, ...]
    shared: dict[str, int]
    tick_groups: int
    tick_ms_avg: float = 0.0
    tick_ms_p99: float = 0.0
    measured_tps: float = 0.0
    dropped_ticks: int = 0
    catch_up_ticks: int = 0
    claims: int = 0
    claim_regions: int = 0
    blackboard_keys: int = 0
    path_cache_hits: int = 0
    path_cache_misses: int = 0
    degraded: bool = False

    @property
    def total(self) -> int:
        """Managed bots."""
        return len(self.bots)

    @property
    def connected(self) -> int:
        """Bots with a live connection."""
        return sum(1 for bot in self.bots if bot.connected)

    @property
    def spawned(self) -> int:
        """Bots that reached the spawn packet."""
        return sum(1 for bot in self.bots if bot.spawned)

    @property
    def chunks(self) -> int:
        """Chunks in shared storage."""
        return self.shared.get("chunks", 0)

    @property
    def chunk_bytes(self) -> int:
        """Estimated bytes held by shared chunk storage."""
        return self.shared.get("bytes", 0)

    def as_dict(self) -> dict[str, object]:
        """Flat dict suitable for logging or a dashboard."""
        return {
            "bots": self.total,
            "connected": self.connected,
            "spawned": self.spawned,
            "chunks": self.chunks,
            "chunk_refs": self.shared.get("refs", 0),
            "sections": self.shared.get("sections", 0),
            "chunk_bytes": self.chunk_bytes,
            "tick_groups": self.tick_groups,
            "tick_ms_avg": self.tick_ms_avg,
            "tick_ms_p99": self.tick_ms_p99,
            "measured_tps": self.measured_tps,
            "dropped_ticks": self.dropped_ticks,
            "catch_up_ticks": self.catch_up_ticks,
            "claims": self.claims,
            "claim_regions": self.claim_regions,
            "blackboard_keys": self.blackboard_keys,
            "path_cache_hits": self.path_cache_hits,
            "path_cache_misses": self.path_cache_misses,
            "degraded": self.degraded,
            "per_bot": [
                {
                    "name": bot.name,
                    "username": bot.username,
                    "connected": bot.connected,
                    "spawned": bot.spawned,
                    "health": bot.health,
                    "food": bot.food,
                    "dimension": bot.dimension,
                    "tick_group": bot.tick_group,
                    "role": bot.role,
                }
                for bot in self.bots
            ],
        }

    def to_prometheus(self) -> str:
        """Prometheus text exposition (no client library required)."""
        lines = [
            "# HELP mcflayer_cluster_bots Bots managed by the cluster",
            "# TYPE mcflayer_cluster_bots gauge",
            f"mcflayer_cluster_bots {self.total}",
            "# HELP mcflayer_cluster_connected Bots with a live connection",
            "# TYPE mcflayer_cluster_connected gauge",
            f"mcflayer_cluster_connected {self.connected}",
            "# HELP mcflayer_cluster_spawned Bots that reached spawn",
            "# TYPE mcflayer_cluster_spawned gauge",
            f"mcflayer_cluster_spawned {self.spawned}",
            "# HELP mcflayer_shared_chunks Chunks in shared storage",
            "# TYPE mcflayer_shared_chunks gauge",
            f"mcflayer_shared_chunks {self.chunks}",
            "# HELP mcflayer_shared_chunk_refs Chunk references held by bots",
            "# TYPE mcflayer_shared_chunk_refs gauge",
            f"mcflayer_shared_chunk_refs {self.shared.get('refs', 0)}",
            "# HELP mcflayer_shared_chunk_bytes Estimated shared chunk memory",
            "# TYPE mcflayer_shared_chunk_bytes gauge",
            f"mcflayer_shared_chunk_bytes {self.chunk_bytes}",
            "# HELP mcflayer_tick_ms Tick callback duration",
            "# TYPE mcflayer_tick_ms gauge",
            f'mcflayer_tick_ms{{quantile="avg"}} {self.tick_ms_avg:.4f}',
            f'mcflayer_tick_ms{{quantile="p99"}} {self.tick_ms_p99:.4f}',
            "# HELP mcflayer_measured_tps Lowest measured tick rate of any group",
            "# TYPE mcflayer_measured_tps gauge",
            f"mcflayer_measured_tps {self.measured_tps:.3f}",
            "# HELP mcflayer_claims Block and region claims",
            "# TYPE mcflayer_claims gauge",
            f"mcflayer_claims {self.claims}",
            f"mcflayer_claim_regions {self.claim_regions}",
            "# HELP mcflayer_path_cache_lookups Path cache lookups",
            "# TYPE mcflayer_path_cache_lookups counter",
            f'mcflayer_path_cache_lookups{{result="hit"}} {self.path_cache_hits}',
            f'mcflayer_path_cache_lookups{{result="miss"}} {self.path_cache_misses}',
            "# HELP mcflayer_bot_connected Per-bot connection state",
            "# TYPE mcflayer_bot_connected gauge",
        ]
        for bot in self.bots:
            label = _escape(bot.name)
            lines.append(f'mcflayer_bot_connected{{bot="{label}"}} {int(bot.connected)}')
        lines.append("# HELP mcflayer_bot_health Per-bot health")
        lines.append("# TYPE mcflayer_bot_health gauge")
        for bot in self.bots:
            label = _escape(bot.name)
            lines.append(f'mcflayer_bot_health{{bot="{label}"}} {bot.health}')
        return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
