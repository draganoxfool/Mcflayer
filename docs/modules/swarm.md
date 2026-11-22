# Swarm (`pyflayer.swarm`)

`BotCluster` supervises bots configured for one server. It can share chunk storage, assign bots to
tick drivers, stagger login attempts, isolate per-bot failures, and expose coordination primitives.

```python
from pyflayer.swarm import BotCluster

cluster = BotCluster("play.example.net", port=25565, tick_groups=2)
cluster.spawn(10)                     # Bot0 .. Bot9, offline auth

async with cluster:
    await cluster.wait_until_ready(timeout=60)
    await cluster.broadcast("ready")
    print(cluster.metrics().as_dict())
```

Every swarm feature is opt-in. A single bot can keep using `pyflayer.Bot` unchanged.

## Shared world

`SharedWorldRegistry` owns one `ChunkStore` per `(server, dimension)`. Each bot gets a `SharedWorld`
view. Each connection decodes its incoming chunk packet before calling `apply_chunk`; the store can
reuse an existing column rather than replacing it when that copy is not newer.

- a view adds a reference when it acquires a chunk;
- block updates mutate the shared column; each bot's packet handler may dispatch its own event;
- a view only reads/updates chunks *it* references, even though other chunks are in the same store;
- `clear()` (respawn, disconnect, dimension change) releases refs; the column is collected when the
  last bot releases it;
- `set_dimension()` releases the old dimension's refs and rebinds the view.

```python
stats = cluster.registry.stats()
# {'worlds': 1, 'chunks': 441, 'refs': 882, 'sections': 7056, 'bytes': ...}
```

The registry is loop-thread-only and lives on the cluster; bots never mutate it from worker threads.
`WorldSnapshot` remains the immutable hand-off for off-loop work.

## Tick groups

Bots are assigned round-robin to `tick_groups` `TickDriver`s. Each driver invokes
`bot.physics_tick()` for the bots assigned to that group.

When the observed p99 group callback duration exceeds `tick_budget_ms` and the configured group limit
has not been reached, the cluster adds a driver and marks `degraded`. Bots created by the cluster
receive their group's driver and do not start private physics loops.

## Login staggering

`LoginStaggerPolicy` serializes login handshakes:

| Option | Default | Meaning |
|---|---|---|
| `min_interval` | `4.0` | Seconds between login starts (Spigot/Paper `connection-throttle`) |
| `max_interval` | `60.0` | Cap after throttle backoff |
| `jitter` | `0.5` | Random extra delay, in seconds |
| `max_concurrency` | `1` | In-flight logins |
| `clock` / `rng` | injected | Deterministic tests |

`record_throttle(reason)` doubles the interval (up to 8×) for throttle-style kicks ("connection
throttled", "logging in too fast", "already connected") and ignores bans. `record_success()` resets
it. `is_throttle_reason(reason)` is available for custom supervision.

```python
policy = LoginStaggerPolicy(min_interval=4.0, jitter=0.75)
cluster = BotCluster("play.example.net", stagger=policy)
```

## Coordination

`ClaimRegistry` prevents two bots from working the same spot:

```python
if cluster.claims.claim("Miner1", BlockPos(10, 64, 10), ttl=120):
    ...  # mine it
cluster.claims.claim_region("Builder", BlockPos(0, 60, 0), BlockPos(16, 70, 16), ttl=600)
cluster.claims.owner_of(pos)
cluster.claims.release_owner("Miner1")
```

Claims are all-or-nothing for regions, reject overlapping regions, expire on the injected clock and
are released automatically when a bot dies or disconnects (`DeathEvent` / `DisconnectEvent`).

`Blackboard` is typed shared state with change events:

```python
cluster.blackboard.set("diamonds", BlockPos(3, 12, 4), owner="Miner1")
value = await cluster.blackboard.wait_for("diamonds", timeout=30)
```

`PathCache` is an LRU cache keyed by `(server, dimension, start, goal, world_version)`, with
`invalidate_world(WorldKey)` for block changes. M6's planner fills it; the swarm only owns the cache.

`RoleRegistry` (via `cluster.assign_role("Miner1", "miner")`) maps at most one role per bot.

## Cluster API

| Member | Meaning |
|---|---|
| `add_bot(auth=None, *, name=None, username=None, …)` | Register one bot |
| `spawn(n, *, name_template="Bot{n}", auth_factory=None)` | Register `n` bots with generated names |
| `start()` / `stop()` | Start supervision and tick drivers; stop and release everything |
| `await wait_until_ready(timeout=…)` | Wait for every bot's Join Game |
| `await broadcast(text, command=False)` | Send chat/command to connected bots; returns the count sent |
| `await run_all(factory)` | Run `factory(bot)` for each bot and gather results |
| `await remove_bot(name)` | Cancel supervision, close and release one bot |
| `bot(name)` / `bots` / `connected_bots` | Lookups |
| `assign_role(name, role)` | Coordination role |
| `metrics()` / `metrics_text()` | `ClusterMetrics` snapshot or Prometheus text |
| `event(coro)` | Register `on_bot_spawn`, `on_bot_kicked`, `on_bot_reconnect`, `on_bot_error` |

```python
@cluster.event
async def on_bot_spawn(event):
    print(event.bot.username, "joined")

@cluster.event
async def on_bot_kicked(event):
    print(event.bot.username, "was kicked:", event.reason)
```

## Supervision and failure isolation

Each registered bot runs a supervisor task. Non-throttle kicks remove that bot by default; set
`remove_on_kick=False` to retry. Network/protocol failures and throttle kicks can be retried with
jittered exponential backoff (`base_backoff`, `max_backoff`, `max_attempts`; `0` means unlimited).

`stop()` is cancellation-safe: supervisors are cancelled, bots closed, chunk refs released, tick
driver tasks cancelled and the cluster event bus closed. No tasks are left behind.

## Metrics

`ClusterMetrics` includes bot health/spawn state, shared chunk counts/refs/estimated bytes, tick
group count, average and p99 tick callback time, measured TPS, dropped/catch-up ticks, claim counts,
blackboard size and path-cache hit/miss counters.

```python
print(cluster.metrics_text())
# mcflayer_cluster_bots 10
# mcflayer_shared_chunks 441
# mcflayer_tick_ms{quantile="p99"} 1.8420
# mcflayer_bot_connected{bot="Bot0"} 1
```

No Prometheus client is required; the text format can be scraped directly or wrapped by a client.

## Bot injection points

M7 adds two backwards-compatible hooks to `pyflayer.Bot`:

```python
bot = Bot("Steve", world=shared_world, tick_driver=cluster_driver)
```

* `world=` accepts any `World` (including `SharedWorld`); the bot will not replace it with a private
  one.
* `tick_driver=` makes the bot skip its private physics loop. The owner calls
  `await bot.physics_tick(tick)` once per driver tick.

## Limitations

- The cluster does not automatically connect claims to action scheduling or path planning. Callers
  coordinate those operations using the exposed APIs.
- Unit tests exercise selected cluster, reference-counting, staggering, coordination, and failure
  scenarios; they do not establish large-fleet performance or live-server behavior.
- Sharing assumes bots connect to the **same server and dimension**. `add_bot(host=…, port=…)` can
  point elsewhere, but then it should get its own registry/view.
- `use_srv` defaults to `False` for clusters because a cluster targets one resolved address; enable
  it for SRV-based servers.
- Microsoft auth is per-bot; the shared `httpx` client / token cache described in the roadmap is not
  wired because online auth remains untested here.
- Server-side connection throttling values differ by implementation; configure `min_interval` for
  your host.

## Tests

```bash
python -m pytest tests/test_swarm.py -q   # 12 tests
python -m pytest -q                       # full suite (323 tests)
```
