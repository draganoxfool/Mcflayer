"""Run a small offline-mode swarm against one server.

Usage:
    python examples/swarm_miners.py [host] [port]

The example logs in four bots with the default 4 s stagger, prints the shared-world and tick
metrics, assigns roles and demonstrates a block claim. It disconnects immediately afterwards.
"""

from __future__ import annotations

import asyncio
import sys

from pyflayer.models import BlockPos
from pyflayer.swarm import BotCluster, BotSpawnEvent


async def main(host: str, port: int) -> None:
    cluster = BotCluster(
        host,
        port=port,
        name_template="Miner{n}",
        tick_groups=2,
        max_tick_groups=4,
    )
    cluster.spawn(4)

    @cluster.event
    async def on_bot_spawn(event: BotSpawnEvent) -> None:
        print(f"spawned {event.bot.username} at {event.bot.position}")

    async with cluster:
        await cluster.wait_until_ready(timeout=120)
        for index, name in enumerate(sorted(cluster.bots)):
            cluster.assign_role(name, "miner" if index % 2 == 0 else "hauler")

        claim = BlockPos(0, 64, 0)
        if cluster.claims.claim("Miner0", claim, ttl=120):
            print(f"Miner0 claimed {claim}")

        cluster.blackboard.set("status", "online", owner="coordinator")
        sent = await cluster.broadcast("ready")
        print(f"broadcast to {sent} bots")
        print(cluster.metrics_text())


if __name__ == "__main__":
    target_host = sys.argv[1] if len(sys.argv) > 1 else "play.example.net"
    target_port = int(sys.argv[2]) if len(sys.argv) > 2 else 25565
    asyncio.run(main(target_host, target_port))
