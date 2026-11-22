# `pyflayer.swarm`

Multi-bot cluster, shared-world, coordination, and metrics exports.

::: pyflayer.swarm
    options:
      show_root_heading: false
      show_root_toc_entry: false

    <!--

Multi-bot clusters, shared worlds, login staggering, coordination and metrics (M7).

```python
from pyflayer.swarm import BotCluster
```

## Cluster

::: pyflayer.swarm.cluster.BotCluster
    options:
      members:
        - add_bot
        - spawn
        - start
        - stop
        - wait_until_ready
        - remove_bot
        - broadcast
        - run_all
        - assign_role
        - event
        - wait_for
        - metrics
        - metrics_text
        - bots
        - connected_bots
        - bot

::: pyflayer.swarm.cluster.BotSpawnEvent

::: pyflayer.swarm.cluster.BotKickedEvent

::: pyflayer.swarm.cluster.BotReconnectEvent

::: pyflayer.swarm.cluster.BotErrorEvent

## Shared world

::: pyflayer.swarm.shared.SharedWorldRegistry

::: pyflayer.swarm.shared.SharedWorld

## Login staggering

::: pyflayer.swarm.stagger.LoginStaggerPolicy

## Coordination

::: pyflayer.swarm.coordinator.ClaimRegistry

::: pyflayer.swarm.coordinator.Claim

::: pyflayer.swarm.coordinator.RegionClaim

::: pyflayer.swarm.coordinator.Blackboard

::: pyflayer.swarm.coordinator.BlackboardChangedEvent

::: pyflayer.swarm.coordinator.PathCache

::: pyflayer.swarm.coordinator.PathCacheStats

::: pyflayer.swarm.coordinator.RoleRegistry

## Metrics

::: pyflayer.swarm.metrics.ClusterMetrics

::: pyflayer.swarm.metrics.BotMetrics
