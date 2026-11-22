# Swarm (`pyflayer.swarm`)

Run dozens of bots against one server without paying for dozens of worlds. A `BotCluster` shares
chunk storage, spreads bots over tick drivers, staggers logins to respect the server's connection
throttle, isolates failures and exposes cooperation primitives (claims, a blackboard and a path
cache).

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
view:

- the first bot to receive a chunk decodes and inserts it;
- every later bot that receives the same chunk only adds a refcount;
- duplicate block updates are applied once, so only one bot emits `BlockUpdateEvent`;
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

Bots are distributed round-robin over `tick_groups` `TickDriver`s. Every driver runs at 20 TPS and
calls `bot.physics_tick()` for its group, so each bot keeps its own 50 ms movement cadence while no
single callback handles all bots.

`tick_budget_ms` (default 50 ms) is monitored through the p99 callback duration. When it is exceeded
and fewer than `max_tick_groups` drivers exist, the cluster adds a group, redistributes bots and logs
a warning. `cluster.metrics().degraded` reports that this happened. Bots constructed by the cluster
already receive the driver that owns their group; they never start private physics loops.

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

Each registered bot runs its own supervisor task. A kick, protocol error or user exception removes
only that bot (non-throttle kicks by default; set `remove_on_kick=False` to retry). Throttle kicks and
ordinary disconnects are retried with jittered exponential backoff
(`base_backoff`, `max_backoff`, `max_attempts`; `0` means unlimited). Exceptions in cluster-event
handlers are isolated by the `EventBus` like any other listener.

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

- **M6 is not implemented.** `PathCache`, claims and roles are ready, but no planner/action scheduler
  consumes them automatically. Coordinated mining requires the caller to claim, dig and release.
- The 50-bot Paper soak, shared-memory benchmark and chaos test from the roadmap were not run in this
  environment; `tests/test_swarm.py` covers three-bot FakeServer scenarios, refcounts, staggering,
  claims, TTLs and failure isolation.
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
