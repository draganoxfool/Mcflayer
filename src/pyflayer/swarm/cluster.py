"""Multi-bot cluster with a shared world, tick driver and login staggering.

:class:`BotCluster` runs many :class:`~pyflayer.bot.Bot` objects against one server with:

* one :class:`~pyflayer.swarm.shared.SharedWorldRegistry` so co-located bots decode a chunk once;
* one or more :class:`~pyflayer.physics.TickDriver` groups (bots are spread across groups so one
  group's callback stays inside the 50 ms tick budget; groups are added with a warning when the
  measured p99 exceeds ``tick_budget_ms``);
* throttle-aware staggered logins;
* per-bot supervision where one bot's kick or exception never cancels the others;
* claims, a blackboard and a shared path cache for cooperation.

Single-bot users never need this module; every feature is opt-in.

Examples:
    >>> cluster = BotCluster("play.example.net", port=25565)
    >>> bots = cluster.spawn(5)          # Bot0 .. Bot4
    >>> async with cluster:
    ...     await cluster.wait_until_ready(timeout=60)
    ...     await cluster.broadcast("hello")
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeVar

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.bot.bot import Bot
from pyflayer.data.loader import McData
from pyflayer.errors import ConnectionClosed, KickedError, ProtocolError
from pyflayer.events.base import Event
from pyflayer.events.bus import EventBus
from pyflayer.events.catalog import DeathEvent, DisconnectEvent, KickEvent, SpawnEvent
from pyflayer.physics.tick import TickDriver
from pyflayer.protocol.auth.base import AuthProvider
from pyflayer.swarm.coordinator import (
    Blackboard,
    ClaimRegistry,
    PathCache,
    RoleRegistry,
)
from pyflayer.swarm.metrics import BotMetrics, ClusterMetrics, percentile
from pyflayer.swarm.shared import SharedWorld, SharedWorldRegistry
from pyflayer.swarm.stagger import LoginStaggerPolicy
from pyflayer.world.world import World

__all__ = [
    "BotCluster",
    "BotErrorEvent",
    "BotKickedEvent",
    "BotReconnectEvent",
    "BotSpawnEvent",
]

log = logging.getLogger("pyflayer.swarm.cluster")

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BotSpawnEvent(Event):
    """A cluster bot reached the spawn packet."""

    bot: Bot


@dataclass(frozen=True, slots=True)
class BotKickedEvent(Event):
    """A cluster bot was kicked by the server."""

    bot: Bot
    reason: str


@dataclass(frozen=True, slots=True)
class BotReconnectEvent(Event):
    """A cluster bot reconnected after a disconnect."""

    bot: Bot


@dataclass(frozen=True, slots=True)
class BotErrorEvent(Event):
    """A supervised bot failed but the cluster kept running."""

    bot: Bot
    error: BaseException


_CLUSTER_EVENTS: dict[str, type[Event]] = {
    cls.__event_name__: cls
    for cls in (BotSpawnEvent, BotKickedEvent, BotReconnectEvent, BotErrorEvent)
}


class BotCluster:
    """Supervises many bots on one server.

    Args:
        host: Server hostname shared by every bot.
        port: Server port.
        version: Minecraft version (all bots must match the shared world data).
        clock: Injected clock for staggering, reconnect backoff and tick drivers.
        stagger: Login staggering policy. The default spaces logins by 4 s.
        tick_groups: Initial number of tick drivers. Bots are spread round-robin.
        max_tick_groups: Upper bound for automatic degradation (defaults to four groups).
        tick_budget_ms: Per-group callback budget; above this the cluster adds a group.
        reconnect: Reconnect supervised bots after a disconnect.
        max_attempts: Maximum consecutive reconnect attempts (``0`` means unlimited).
        base_backoff: First reconnect delay, doubled per attempt.
        max_backoff: Reconnect delay cap.
        auto_respawn: Passed to every bot.
        world_sharing: Share chunk storage between co-located bots.
        remove_on_kick: Remove a bot after a non-throttle kick instead of retrying.
        name_template: Name/username template; ``{n}`` is the bot index.
        rng: Random source for jitter (inject a seeded ``random.Random`` in tests).
    """

    def __init__(
        self,
        host: str,
        *,
        port: int = 25565,
        version: str = "1.8.9",
        clock: Clock | None = None,
        stagger: LoginStaggerPolicy | None = None,
        tick_groups: int = 1,
        max_tick_groups: int | None = None,
        tick_budget_ms: float = 50.0,
        reconnect: bool = True,
        max_attempts: int = 0,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
        auto_respawn: bool = True,
        use_srv: bool = False,
        world_sharing: bool = True,
        remove_on_kick: bool = True,
        name_template: str = "Bot{n}",
        rng: random.Random | None = None,
    ) -> None:
        if not host:
            raise ValueError("host is required")
        if tick_groups < 1:
            raise ValueError("tick_groups must be at least 1")
        if max_tick_groups is not None and max_tick_groups < tick_groups:
            raise ValueError("max_tick_groups must be >= tick_groups")
        self.host = host
        self.port = port
        self.version = version
        self.clock = clock or MonotonicClock()
        self.rng = rng or random.Random()
        self.stagger = stagger or LoginStaggerPolicy(clock=self.clock, rng=self.rng)
        self.tick_budget_ms = tick_budget_ms
        self.max_tick_groups = (
            max_tick_groups if max_tick_groups is not None else max(4, tick_groups)
        )
        self.reconnect = reconnect
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.auto_respawn = auto_respawn
        self.use_srv = use_srv
        self.world_sharing = world_sharing
        self.remove_on_kick = remove_on_kick
        self.name_template = name_template

        self.mc = McData.load(version)
        self.registry: SharedWorldRegistry | None = (
            SharedWorldRegistry(self.mc, server=f"{host}:{port}") if world_sharing else None
        )
        self.events = EventBus(clock=self.clock)
        self.claims = ClaimRegistry(clock=self.clock)
        self.blackboard = Blackboard(clock=self.clock)
        self.path_cache = PathCache()
        self.roles = RoleRegistry()

        self._drivers: list[TickDriver] = [TickDriver(self.clock) for _ in range(tick_groups)]
        self._driver_tasks: dict[int, asyncio.Task[None]] = {}
        self._bots: dict[str, Bot] = {}
        self._indices: dict[str, int] = {}
        self._views: dict[str, SharedWorld] = {}
        self._tokens: dict[str, object] = {}
        self._supervisors: dict[str, asyncio.Task[None]] = {}
        self._tick_ms: deque[float] = deque(maxlen=600)
        self._counter = 0
        self._bot_ids = 0
        self._started = False
        self._stopping = False
        self.degraded = False

    # ------------------------------------------------------------------ registration
    @property
    def bots(self) -> Mapping[str, Bot]:
        """All managed bots keyed by cluster name."""
        return MappingProxyType(self._bots)

    @property
    def connected_bots(self) -> tuple[Bot, ...]:
        """Bots with a live connection."""
        return tuple(bot for bot in self._bots.values() if bot.connected)

    def bot(self, name: str) -> Bot:
        """Look up a managed bot by cluster name.

        Raises:
            KeyError: When no bot has that name.
        """
        return self._bots[name]

    def _next_name(self) -> str:
        while True:
            index = self._counter
            self._counter += 1
            if "{n}" in self.name_template or "{i}" in self.name_template:
                candidate = self.name_template.format(n=index, i=index)
            else:
                candidate = f"{self.name_template}{index}"
            if candidate not in self._bots:
                return candidate

    def add_bot(
        self,
        auth: AuthProvider | None = None,
        *,
        name: str | None = None,
        username: str | None = None,
        host: str | None = None,
        port: int | None = None,
        version: str | None = None,
        auto_respawn: bool | None = None,
        join_timeout: float | None = None,
        world: World | None = None,
    ) -> Bot:
        """Create and register a bot (it connects when the cluster starts).

        Args:
            auth: Authentication provider; defaults to offline auth with ``username``.
            name: Cluster name; defaults to the next value from ``name_template``.
            username: Offline username; defaults to the cluster name.
            host: Override the cluster host (a different server shares no chunks).
            port: Override the cluster port.
            version: Override the Minecraft version.
            auto_respawn: Override the cluster default.
            join_timeout: Passed to the bot.
            world: Explicit world; defaults to a shared view when sharing is enabled.
        """
        bot_name = name or username or self._next_name()
        if bot_name in self._bots:
            raise ValueError(f"bot {bot_name!r} already exists")
        index = len(self._indices)
        self._indices[bot_name] = index

        bot_host = host or self.host
        bot_port = port if port is not None else self.port
        if bot_host != self.host and self.world_sharing and world is None:
            log.warning("%s uses a different host; shared worlds assume one server", bot_name)
        if world is None and self.registry is not None:
            self._bot_ids += 1
            world = self.registry.view(bot_id=self._bot_ids)
            self._views[bot_name] = world
        driver = self._drivers[index % len(self._drivers)]
        bot = Bot(
            username=username if username is not None else (bot_name if auth is None else None),
            host=bot_host,
            port=bot_port,
            version=version or self.version,
            auth=auth,
            clock=self.clock,
            use_srv=self.use_srv,
            auto_respawn=self.auto_respawn if auto_respawn is None else auto_respawn,
            reconnect=False,  # the cluster supervisor owns reconnect policy
            join_timeout=30.0 if join_timeout is None else join_timeout,
            world=world,
            tick_driver=driver,
        )
        self._bots[bot_name] = bot
        self._bind_events(bot_name, bot)
        return bot

    def spawn(
        self,
        count: int,
        *,
        name_template: str | None = None,
        auth_factory: Callable[[int], AuthProvider | None] | None = None,
        **options: object,
    ) -> list[Bot]:
        """Add ``count`` bots with generated names and return them."""
        if count < 1:
            return []
        previous = self.name_template
        if name_template is not None:
            self.name_template = name_template
        try:
            created: list[Bot] = []
            for index in range(count):
                auth = auth_factory(index) if auth_factory is not None else None
                created.append(
                    self.add_bot(
                        auth,
                        name=self._next_name(),
                        **options,  # type: ignore[arg-type]
                    )
                )
            return created
        finally:
            self.name_template = previous

    async def remove_bot(self, name: str, *, close: bool = True) -> None:
        """Cancel a bot's supervisor, close it and release its shared state."""
        task = self._supervisors.pop(name, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        bot = self._bots.get(name)
        if bot is not None and close:
            await self._close_bot(bot)
        self._detach(name)
        self._bots.pop(name, None)
        self._indices.pop(name, None)

    async def _close_bot(self, bot: Bot) -> None:
        try:
            await bot.close()
        except Exception:  # pragma: no cover - close is best effort during teardown
            log.debug("bot close failed", exc_info=True)

    def _bind_events(self, name: str, bot: Bot) -> None:
        token = object()
        self._tokens[name] = token
        bot.events.subscribe(
            SpawnEvent,
            lambda event: self.events.dispatch(BotSpawnEvent(bot)),
            owner=token,
        )
        bot.events.subscribe(
            KickEvent,
            lambda event: self.events.dispatch(BotKickedEvent(bot, event.reason_text)),
            owner=token,
        )
        bot.events.subscribe(
            DeathEvent,
            lambda event: self._release_owner(name),
            owner=token,
        )
        bot.events.subscribe(
            DisconnectEvent,
            lambda event: self._release_owner(name),
            owner=token,
        )

    def _release_owner(self, name: str) -> None:
        self.claims.release_owner(name)
        self.roles.release(name)

    def _detach(self, name: str) -> None:
        bot = self._bots.get(name)
        token = self._tokens.pop(name, None)
        if bot is not None and token is not None:
            bot.events.unsubscribe_owner(token)
        view = self._views.pop(name, None)
        if view is not None:
            if self.registry is not None:
                self.registry.release(view)
            else:  # pragma: no cover - views only exist with a registry
                view.clear()
        self._release_owner(name)

    # ------------------------------------------------------------------ lifecycle
    async def __aenter__(self) -> BotCluster:
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    def start(self) -> None:
        """Start tick drivers and bot supervisors. Returns immediately."""
        if self._started:
            return
        self._stopping = False
        self._started = True
        self._ensure_driver_tasks()
        for name, bot in self._bots.items():
            if bot.closed:
                continue
            task = self._supervisors.get(name)
            if task is None or task.done():
                self._supervisors[name] = asyncio.create_task(
                    self._supervise(name), name=f"pyflayer-swarm-{name}"
                )

    async def wait_until_ready(
        self, *, timeout: float = 30.0  # noqa: ASYNC109 - public readiness wait
    ) -> None:
        """Wait until every managed bot has spawned.

        Raises:
            TimeoutError: When any bot does not spawn within ``timeout``.
        """
        if not self._bots:
            return
        await asyncio.wait_for(
            asyncio.gather(*(bot.wait_until_ready() for bot in self._bots.values())),
            timeout,
        )

    async def stop(self) -> None:
        """Stop supervison, close every bot and release shared chunks."""
        if self._stopping:
            return
        self._stopping = True
        for driver in self._drivers:
            driver.stop()
        current = asyncio.current_task()
        supervisors = [
            task
            for task in self._supervisors.values()
            if task is not current and not task.done()
        ]
        for task in supervisors:
            task.cancel()
        if supervisors:
            await asyncio.gather(*supervisors, return_exceptions=True)
        self._supervisors.clear()
        bots = list(self._bots.values())
        await asyncio.gather(*(bot.close() for bot in bots), return_exceptions=True)
        for name in list(self._bots):
            self._detach(name)
        self._bots.clear()
        self._indices.clear()
        driver_tasks = list(self._driver_tasks.values())
        for task in driver_tasks:
            task.cancel()
        if driver_tasks:
            await asyncio.gather(*driver_tasks, return_exceptions=True)
        self._driver_tasks.clear()
        await self.events.aclose()
        self._started = False

    # ------------------------------------------------------------------ supervision
    async def _supervise(self, name: str) -> None:
        bot = self._bots.get(name)
        if bot is None:
            return
        attempts = 0
        connected_once = False
        while not self._stopping:
            if bot.closed or name not in self._bots:
                return
            try:
                async with self.stagger.slot():
                    await bot.connect()
                self.stagger.record_success()
                attempts = 0
                if connected_once:
                    self.events.dispatch(BotReconnectEvent(bot))
                connected_once = True
                await bot.run()
            except asyncio.CancelledError:
                raise
            except KickedError:
                reason = str(bot.kick_reason or "kicked")
                self.stagger.record_throttle(reason)
                throttled = self.stagger.is_throttle_reason(reason)
                if self.remove_on_kick and not throttled:
                    await self._retire(name)
                    return
                # Throttle kicks are retried with the policy's longer interval.
            except (ConnectionClosed, ProtocolError, TimeoutError, OSError) as exc:
                log.warning("%s disconnected: %s", name, exc)
                self.events.dispatch(BotErrorEvent(bot, exc))
            except Exception as exc:  # isolate user/protocol bugs to one bot
                log.exception("%s failed; removing it from the cluster", name)
                self.events.dispatch(BotErrorEvent(bot, exc))
                await self._retire(name)
                return
            if self._stopping or name not in self._bots:
                return
            if bot.closed:
                await self._retire(name)
                return
            if not self.reconnect:
                await self._retire(name)
                return
            attempts += 1
            if self.max_attempts and attempts > self.max_attempts:
                await self._retire(name)
                return
            delay = min(self.max_backoff, self.base_backoff * 2 ** (attempts - 1))
            delay *= 1.0 + self.rng.random() * 0.25
            await self.clock.sleep(delay)

    async def _retire(self, name: str) -> None:
        """Remove a bot from inside its own supervisor (without cancelling that task)."""
        bot = self._bots.pop(name, None)
        self._indices.pop(name, None)
        self._supervisors.pop(name, None)
        if bot is not None:
            await bot.close()
        self._detach(name)

    # ------------------------------------------------------------------ ticking
    def _ensure_driver_tasks(self) -> None:
        for index in range(len(self._drivers)):
            task = self._driver_tasks.get(index)
            if task is None or task.done():
                self._driver_tasks[index] = asyncio.create_task(
                    self._run_driver(index), name=f"pyflayer-swarm-tick-{index}"
                )

    async def _run_driver(self, index: int) -> None:
        driver = self._drivers[index]

        async def callback(tick: int) -> None:
            await self._tick_group(index, tick)

        try:
            await driver.run(callback)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - a driver crash is logged, not silent
            log.exception("tick group %d failed", index)

    async def _tick_group(self, group: int, tick: int) -> None:
        started = self.clock.monotonic()
        groups = len(self._drivers)
        for name, bot in list(self._bots.items()):
            if self._stopping or bot.closed:
                continue
            if self._indices.get(name, 0) % groups != group:
                continue
            try:
                await bot.physics_tick(tick)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception("physics tick failed for %s", name)
                self.events.dispatch(BotErrorEvent(bot, exc))
        duration = (self.clock.monotonic() - started) * 1000.0
        self._tick_ms.append(duration)
        if group == 0:
            self._maybe_degrade()

    def _maybe_degrade(self) -> None:
        if len(self._tick_ms) < 100 or len(self._drivers) >= self.max_tick_groups:
            return
        if percentile(list(self._tick_ms), 0.99) <= self.tick_budget_ms:
            return
        self._drivers.append(TickDriver(self.clock))
        self._ensure_driver_tasks()
        self.degraded = True
        log.warning(
            "tick p99 %.1f ms exceeded %.1f ms; sharding to %d tick groups",
            percentile(list(self._tick_ms), 0.99),
            self.tick_budget_ms,
            len(self._drivers),
        )

    # ------------------------------------------------------------------ actions
    async def broadcast(self, message: str, *, command: bool = False) -> int:
        """Send chat (or a command) to every connected bot; return the number sent."""
        bots = self.connected_bots
        if not bots:
            return 0
        if command:
            results = await asyncio.gather(
                *(bot.send_command(message) for bot in bots), return_exceptions=True
            )
        else:
            results = await asyncio.gather(
                *(bot.chat(message) for bot in bots), return_exceptions=True
            )
        sent = 0
        for bot, result in zip(bots, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("broadcast to %s failed: %s", bot.username, result)
            else:
                sent += 1
        return sent

    async def run_all(self, coro_factory: Callable[[Bot], Awaitable[T]]) -> list[T]:
        """Run ``coro_factory(bot)`` for every managed bot and gather the results."""
        return list(await asyncio.gather(*(coro_factory(bot) for bot in self._bots.values())))

    def assign_role(self, name: str, role: str) -> None:
        """Assign a cooperation role to a bot."""
        self.roles.assign(name, role)

    # ------------------------------------------------------------------ events
    def event(self, coro: Callable[..., object]) -> Callable[..., object]:
        """Register an ``on_bot_spawn`` / ``on_bot_kicked`` style cluster handler."""
        name = getattr(coro, "__name__", "")
        event_type = _CLUSTER_EVENTS.get(name)
        if event_type is None:
            raise ValueError(f"unknown cluster event handler {name!r}")
        self.events.subscribe(event_type, coro)
        return coro

    async def wait_for(
        self,
        event: type,
        *,
        check: Callable[[object], bool] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - public event-wait API
    ) -> object:
        """Delegate to :meth:`EventBus.wait_for`."""
        return await self.events.wait_for(event, check=check, timeout=timeout)

    # ------------------------------------------------------------------ metrics
    def metrics(self) -> ClusterMetrics:
        """Snapshot of bot health, shared memory and tick timing."""
        bots = tuple(
            BotMetrics(
                name=name,
                username=bot.username,
                connected=bot.connected,
                spawned=bot.spawned,
                dead=bot.dead,
                health=bot.health,
                food=bot.food,
                dimension=bot.dimension,
                position=None
                if bot.position is None
                else (bot.position.x, bot.position.y, bot.position.z),
                tick_group=self._indices.get(name, 0) % len(self._drivers),
                role=self.roles.role_of(name),
            )
            for name, bot in self._bots.items()
        )
        durations = list(self._tick_ms)
        tick_ms_avg = sum(durations) / len(durations) if durations else 0.0
        tick_ms_p99 = percentile(durations, 0.99)
        measured = [driver.measured_tps for driver in self._drivers if driver.tick > 0]
        path_stats = self.path_cache.stats
        return ClusterMetrics(
            bots=bots,
            shared=dict(self.registry.stats()) if self.registry is not None else {},
            tick_groups=len(self._drivers),
            tick_ms_avg=tick_ms_avg,
            tick_ms_p99=tick_ms_p99,
            measured_tps=min(measured) if measured else 0.0,
            dropped_ticks=sum(driver.dropped_ticks for driver in self._drivers),
            catch_up_ticks=sum(driver.catch_up_ticks for driver in self._drivers),
            claims=len(self.claims.claims()),
            claim_regions=len(self.claims.regions()),
            blackboard_keys=len(self.blackboard),
            path_cache_hits=path_stats.hits,
            path_cache_misses=path_stats.misses,
            degraded=self.degraded,
        )

    def metrics_text(self) -> str:
        """Prometheus text for the current snapshot."""
        return self.metrics().to_prometheus()

    def __len__(self) -> int:
        return len(self._bots)

    def __repr__(self) -> str:
        return (
            f"BotCluster(host={self.host!r}, bots={len(self._bots)}, "
            f"groups={len(self._drivers)}, started={self._started})"
        )
