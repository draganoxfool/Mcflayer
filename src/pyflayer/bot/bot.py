"""Bot composition root: protocol, events, world state, inventory and physics.

The bot owns the 20 TPS physics tick (M4), emits vanilla-style movement packets and reconciles
server positions/teleports. The action scheduler arrives in a later milestone.

Examples:
    >>> from pyflayer.bot import Bot
    >>> async def main():
    ...     bot = Bot("Steve", host="play.pika-network.net")
    ...     await bot.connect()
    ...     await bot.chat("/register secret secret")
    ...     await bot.run()
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from pyflayer._internal.clock import Clock, MonotonicClock
from pyflayer.bot import interactions as _interactions
from pyflayer.bot import windows as _windows
from pyflayer.bot.inventory import (
    CURSOR_EVENT_SLOT,
    CURSOR_SLOT,
    HOTBAR_START,
    ClickMode,
    Inventory,
)
from pyflayer.bot.movement import MovementPacket, MovementTracker
from pyflayer.data.loader import McData
from pyflayer.errors import ConnectionClosed, KickedError, ProtocolError
from pyflayer.events.bus import EventBus, Expectation
from pyflayer.events.catalog import (
    BlockUpdateEvent,
    ChatEvent,
    ChunkLoadEvent,
    ConnectEvent,
    DeathEvent,
    DimensionChangeEvent,
    DisconnectEvent,
    EntityGoneEvent,
    EntityMetadataEvent,
    EntityMoveEvent,
    EntitySpawnEvent,
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
from pyflayer.models.enums import Face
from pyflayer.models.items import ItemStack
from pyflayer.models.text import ChatComponent
from pyflayer.models.vec3 import BlockPos, ChunkPos, Vec3
from pyflayer.physics import ControlState, PhysicsEngine, PlayerState, TickDriver
from pyflayer.protocol.auth.base import AuthProvider
from pyflayer.protocol.client import ProtocolClient
from pyflayer.protocol.native.chunk_data import decode_legacy_chunk
from pyflayer.protocol.protodef import Packet
from pyflayer.world import ChunkColumn, EntityTracker, World

__all__ = ["Bot", "BotState", "PlayerInfo"]

log = logging.getLogger("pyflayer.bot")


@dataclass(slots=True)
class PlayerInfo:
    """One tab-list entry."""

    uuid: str
    name: str | None = None
    ping: int | None = None
    game_mode: int | None = None
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class BotState:
    """Immutable snapshot of the bot's player state."""

    username: str
    uuid: str | None
    entity_id: int | None
    position: Vec3 | None
    yaw: float
    pitch: float
    health: float
    food: int
    saturation: float
    game_mode: int | None
    dimension: int | None
    dead: bool


class Bot:
    """A connected Minecraft player.

    Args:
        username: Offline username (ignored when ``auth`` provides a session name).
        host: Server hostname.
        port: Server port.
        version: Minecraft version.
        auth: Authentication provider.
        clock: Injected clock used for reconnects and chat rate limiting.
        use_srv: Resolve SRV records.
        auto_respawn: Send ``client_command(perform_respawn)`` on death.
        reconnect: Reconnect with exponential backoff when ``run()`` loses the connection.
        max_backoff: Upper bound for reconnect delay, in seconds.
        join_timeout: How long :meth:`connect` waits for Join Game.
    """

    __slots__ = (
        "_backoff",
        "_chat",
        "_closed",
        "_join_event",
        "_jump_next",
        "_last_sneaking",
        "_last_sprinting",
        "_physics_task",
        "_ready",
        "_teleport_id",
        "_teleport_pending",
        "attributes",
        "auth",
        "auto_respawn",
        "client",
        "clock",
        "controls",
        "dead",
        "dimension",
        "entities",
        "entity_id",
        "events",
        "experience",
        "food",
        "game_mode",
        "health",
        "host",
        "inventory",
        "join_timeout",
        "joined",
        "kick_reason",
        "max_backoff",
        "movement",
        "physics",
        "physics_state",
        "pitch",
        "players",
        "port",
        "position",
        "reconnect",
        "saturation",
        "spawn_position",
        "spawned",
        "tick_driver",
        "use_srv",
        "username",
        "uuid",
        "version",
        "world",
        "yaw",
    )

    def __init__(
        self,
        username: str | None = None,
        *,
        host: str = "",
        port: int = 25565,
        version: str = "1.8.9",
        auth: AuthProvider | None = None,
        clock: Clock | None = None,
        use_srv: bool = True,
        auto_respawn: bool = True,
        reconnect: bool = False,
        max_backoff: float = 30.0,
        join_timeout: float = 20.0,
    ) -> None:
        self.username = username or ""
        self.host = host
        self.port = port
        self.version = version
        self.auth = auth
        self.clock = clock or MonotonicClock()
        self.use_srv = use_srv
        self.auto_respawn = auto_respawn
        self.reconnect = reconnect
        self.max_backoff = max_backoff
        self.join_timeout = join_timeout
        self.events = EventBus(clock=self.clock)
        self.client: ProtocolClient | None = None
        self.uuid: str | None = None
        self.entity_id: int | None = None
        self.position: Vec3 | None = None
        self.spawn_position: BlockPos | None = None
        self.yaw = 0.0
        self.pitch = 0.0
        self.health = 20.0
        self.food = 20
        self.saturation = 5.0
        self.game_mode: int | None = None
        self.dimension: int | None = None
        self.dead = False
        self.joined = False
        self.spawned = False
        self.players: dict[str, PlayerInfo] = {}
        mc = McData.load(version)
        self.world = World(mc)
        self.entities = EntityTracker(mc)
        self.inventory = Inventory()
        self.experience: tuple[float, int, int] = (0.0, 0, 0)
        self.attributes: dict[str, float] = {}
        self.kick_reason: ChatComponent | None = None
        self.physics = PhysicsEngine()
        self.physics_state: PlayerState | None = None
        self.controls = ControlState()
        self.movement = MovementTracker()
        self.tick_driver: TickDriver | None = None
        self._physics_task: asyncio.Task[None] | None = None
        self._jump_next = False
        self._last_sprinting = False
        self._last_sneaking = False
        self._teleport_pending = False
        self._teleport_id: int | None = None
        self._join_event: JoinEvent | None = None
        from pyflayer.bot.chat import ChatQueue

        self._chat = ChatQueue(self._send_chat_line, clock=self.clock)
        self._ready = asyncio.Event()
        self._closed = False
        self._backoff = 1.0

    # ------------------------------------------------------------------ properties
    @property
    def connected(self) -> bool:
        """True when the protocol client is connected."""
        return self.client is not None and self.client.connected

    @property
    def state(self) -> BotState:
        """Snapshot of the mutable player state."""
        return BotState(
            username=self.username,
            uuid=self.uuid,
            entity_id=self.entity_id,
            position=self.position,
            yaw=self.yaw,
            pitch=self.pitch,
            health=self.health,
            food=self.food,
            saturation=self.saturation,
            game_mode=self.game_mode,
            dimension=self.dimension,
            dead=self.dead,
        )

    # ------------------------------------------------------------------ lifecycle
    async def connect(self, *, host: str | None = None, port: int | None = None) -> JoinEvent:
        """Log in and wait for Join Game.

        Returns:
            The :class:`JoinEvent` for this session.

        Raises:
            TimeoutError: When Join Game does not arrive within ``join_timeout``.
            KickedError: When the server kicks during login.
            LoginRejected: When the login is refused.
        """
        if host is not None:
            self.host = host
        if port is not None:
            self.port = port
        if not self.host:
            raise ValueError("host is required")
        self._closed = False
        self._join_event = None
        self.joined = False
        self.spawned = False
        self.dead = False
        self.health = 20.0
        self.food = 20
        self.saturation = 5.0
        self._ready.clear()
        self.kick_reason = None
        self.world.clear()
        self.entities.clear()
        self.inventory.clear()
        self.players.clear()
        self.experience = (0.0, 0, 0)
        self.attributes.clear()
        self._reset_physics()
        client = ProtocolClient(
            self.host,
            self.username or None,
            port=self.port,
            version=self.version,
            auth=self.auth,
            use_srv=self.use_srv,
            clock=self.clock,
        )
        self.client = client
        try:
            session = await client.connect()
            if self.world.mc is not client.mc:
                self.world = World(client.mc)
                self.entities = EntityTracker(client.mc)
            self.username = session.username
            self.uuid = session.uuid
            self.events.dispatch(
                ConnectEvent(host=self.host, port=self.port, protocol=client.protocol)
            )
            self.events.dispatch(LoginEvent(username=session.username, uuid=session.uuid))

            async with asyncio.timeout(self.join_timeout):
                async for packet in client.packets():
                    await self._handle(packet)
                    if self.joined:
                        break
            if not self.joined or self._join_event is None:
                raise TimeoutError("server did not send Join Game")
        except BaseException:
            # Login or join failures must not leak a half-open socket or tick loop.
            self._join_event = None
            await self._close_client()
            raise
        self._backoff = 1.0
        return self._join_event

    async def wait_until_ready(self) -> None:
        """Wait until Join Game has been handled."""
        await self._ready.wait()

    async def run(self) -> None:
        """Read and handle packets until disconnected.

        With ``reconnect=True`` the bot reconnects with exponential backoff (1 s doubling to
        ``max_backoff``); auth errors and bans stop the loop.
        """
        assert self.client is not None, "call connect() before run()"
        while not self._closed:
            if self.client is None:
                # A failed reconnect leaves client=None; retry with backoff instead of
                # dereferencing it on the next pass.
                delay = min(self.max_backoff, self._backoff) * (1.0 + random.random() * 0.25)
                log.info("reconnecting in %.1fs", delay)
                try:
                    await self.clock.sleep(delay)
                    await self.connect()
                except (ConnectionClosed, ProtocolError, TimeoutError) as exc:
                    log.warning("reconnect failed: %s", exc)
                    self._backoff = min(self.max_backoff, self._backoff * 2)
                    self.events.dispatch(DisconnectEvent(reason=str(exc), error=exc))
                    continue
                else:
                    self._backoff = 1.0
            error: BaseException | None = None
            try:
                async for packet in self.client.packets():
                    await self._handle(packet)
            except KickedError as exc:
                error = exc
            except ConnectionClosed as exc:
                error = exc
            except ProtocolError as exc:
                error = exc
                log.warning("protocol error: %s", exc)
            self.events.dispatch(
                DisconnectEvent(reason=str(error) if error else "closed", error=error)
            )
            await self._close_client()
            if isinstance(error, KickedError):
                raise error
            if self._closed or not self.reconnect:
                return

    async def close(self) -> None:
        """Close the connection and stop reconnecting. Idempotent."""
        self._closed = True
        await self._close_client()

    async def __aenter__(self) -> Bot:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _close_client(self) -> None:
        await self._stop_physics()
        client = self.client
        if client is not None:
            await client.close()
            self.client = None
        self.joined = False
        self.spawned = False
        self._ready.clear()

    # ------------------------------------------------------------------ actions
    async def chat(self, message: str) -> None:
        """Send chat (rate limited, split at 256 characters).

        A leading ``/`` is sent as a server command. Prefer :meth:`send_command` for clarity;
        untrusted text should be sanitized before reaching this method.
        """
        await self._chat.send(message, allow_commands=True)

    async def send_command(self, command: str) -> None:
        """Send a command, adding the leading slash when missing.

        Commands are not split, so a multi-line command reaches the server as one packet.
        """
        text = command if command.startswith("/") else f"/{command}"
        await self._chat.send(text, allow_commands=True)

    async def _send_chat_line(self, line: str) -> None:
        if self.client is None:
            raise ConnectionClosed("not connected")
        await self.client.send_chat(line)

    async def _send_play(self, name: str, fields: dict[str, object]) -> None:
        """Send one play packet, failing clearly when disconnected."""
        if self.client is None:
            raise ConnectionClosed("not connected")
        await self.client.send_packet(name, fields)

    # ------------------------------------------------------------------ inventory actions
    async def select_hotbar(self, slot: int) -> None:
        """Select hotbar slot ``0..8`` (``held_item_slot``)."""
        await _windows.select_hotbar(self, slot)

    async def click_slot(
        self,
        slot: int,
        *,
        button: int = 0,
        mode: int | ClickMode = ClickMode.LEFT,
        window_id: int = 0,
        item: ItemStack | None = None,
    ) -> int:
        """Send a raw 1.8 ``window_click`` and return its action number.

        ``slot`` is the raw window slot. For every container the container slots come first,
        followed by the copied player inventory (27 main slots, then 9 hotbar slots). The server
        answers with ``set_slot``/``window_items``; slot contents are not changed optimistically.
        """
        return await _windows.click_slot(
            self,
            slot,
            button=button,
            mode=mode,
            window_id=window_id,
            item=item,
        )

    async def shift_click_slot(self, slot: int, *, button: int = 0, window_id: int = 0) -> int:
        """Shift-click a slot (quick-move between container and inventory)."""
        return await _windows.shift_click_slot(self, slot, button=button, window_id=window_id)

    async def drop_slot(self, slot: int, *, all: bool = False, window_id: int = 0) -> int:
        """Drop one item or the whole stack from a slot."""
        return await _windows.drop_slot(self, slot, all=all, window_id=window_id)

    async def close_window(self, window_id: int = 0) -> None:
        """Close a window server-side and drop its local state."""
        await _windows.close_window(self, window_id)

    # ------------------------------------------------------------------ block and item actions
    async def swing_arm(self) -> None:
        """Play the main-hand swing animation (``arm_animation``)."""
        await _interactions.swing_arm(self)

    async def use_item(self) -> None:
        """Use the held item without targeting a block."""
        await _interactions.use_item(self)

    async def place_block(
        self,
        pos: BlockPos,
        *,
        face: Face | int = Face.UP,
        cursor: tuple[int, int, int] = (8, 8, 8),
    ) -> None:
        """Right-click a block position with the held item (``block_place``)."""
        await _interactions.place_block(self, pos, face=face, cursor=cursor)

    async def start_digging(self, pos: BlockPos, *, face: Face | int = Face.UP) -> None:
        """Start breaking a block (``block_dig`` status 0)."""
        await _interactions.start_digging(self, pos, face=face)

    async def finish_digging(self, pos: BlockPos, *, face: Face | int = Face.UP) -> None:
        """Finish breaking a block (``block_dig`` status 2)."""
        await _interactions.finish_digging(self, pos, face=face)

    async def cancel_digging(self, pos: BlockPos, *, face: Face | int = Face.UP) -> None:
        """Abort a break in progress (``block_dig`` status 1)."""
        await _interactions.cancel_digging(self, pos, face=face)

    async def break_block(
        self,
        pos: BlockPos,
        *,
        face: Face | int = Face.UP,
        delay: float = 0.0,
    ) -> None:
        """Send start and finish digging, optionally waiting ``delay`` seconds.

        Survival break time depends on block hardness, tool and effects; this helper does not
        calculate it. Pass ``delay`` or drive start/finish yourself. Creative mode accepts an
        immediate finish.
        """
        await _interactions.break_block(self, pos, face=face, delay=delay)

    async def respawn(self) -> None:
        """Ask the server to respawn the player."""
        if self.client is None:
            raise ConnectionClosed("not connected")
        await self.client.send_packet("client_command", {"payload": "perform_respawn"})

    # ------------------------------------------------------------------ movement controls
    def set_movement(
        self,
        forward: float = 0.0,
        strafe: float = 0.0,
        *,
        sprint: bool = False,
        sneak: bool = False,
    ) -> None:
        """Set continuous movement input for the next physics tick.

        ``forward`` is positive towards the facing direction, ``strafe`` positive to the left. The
        values are clamped to ``-1..1`` by the engine.
        """
        self.controls = replace(
            self.controls,
            forward=forward,
            strafe=strafe,
            sprint=sprint,
            sneak=sneak,
        )

    def stop_movement(self) -> None:
        """Clear movement input while keeping the current look direction."""
        self.controls = ControlState(yaw=self.controls.yaw, pitch=self.controls.pitch)
        self._jump_next = False

    def look(self, *, yaw: float | None = None, pitch: float | None = None) -> None:
        """Set the look direction used by the next physics tick."""
        self.controls = replace(
            self.controls,
            yaw=self.controls.yaw if yaw is None else yaw,
            pitch=self.controls.pitch if pitch is None else pitch,
        )

    def jump(self) -> None:
        """Request one jump on the next physics tick."""
        self._jump_next = True

    @property
    def on_ground(self) -> bool:
        """True when the last physics tick ended on the ground."""
        return self.physics_state.on_ground if self.physics_state is not None else False

    @property
    def teleport_confirm_supported(self) -> bool:
        """True when this version's server teleports carry an id (1.9+)."""
        return self.world.mc.features.teleport_confirm

    # ------------------------------------------------------------------ physics loop
    def _reset_physics(self) -> None:
        self.physics_state = None
        self.controls = ControlState()
        self.movement = MovementTracker()
        self.tick_driver = None
        self._jump_next = False
        self._last_sprinting = False
        self._last_sneaking = False
        self._teleport_pending = False
        self._teleport_id = None

    async def _stop_physics(self) -> None:
        task = self._physics_task
        self._physics_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.tick_driver is not None:
            self.tick_driver.stop()
            self.tick_driver = None

    def _ensure_physics_loop(self) -> None:
        if self.joined is False or self.client is None:
            return
        if self._physics_task is not None and not self._physics_task.done():
            return
        self.tick_driver = TickDriver(self.clock)
        self._physics_task = asyncio.create_task(
            self._run_physics(self.tick_driver), name=f"pyflayer-physics-{id(self):x}"
        )

    async def _run_physics(self, driver: TickDriver) -> None:
        try:
            await driver.run(self._physics_tick)
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            log.debug("physics loop stopped: connection closed")
        except Exception:
            log.exception("physics loop failed")

    async def _physics_tick(self, tick: int) -> None:
        state = self.physics_state
        if state is None:
            return
        if self._teleport_pending:
            await self._send_position_confirmation(state)
            self._teleport_pending = False
            return
        if not self.spawned or self.dead:
            return
        if not self.world.is_loaded(state.position.floored().chunk):
            return

        controls = self.controls
        if self._jump_next:
            controls = replace(controls, jump=True)
            self._jump_next = False
        state = self.physics.step(state, controls, self.world)
        self.physics_state = state
        self.position = state.position
        self.yaw = state.yaw
        self.pitch = state.pitch

        await self._sync_action_state(state)
        packet = self.movement.observe(state.position, state.yaw, state.pitch, state.on_ground)
        if packet is not None:
            await self._send_movement(packet)
        self.events.dispatch(
            PhysicsTickEvent(tick=tick, position=state.position, on_ground=state.on_ground)
        )

    async def _sync_action_state(self, state: PlayerState) -> None:
        """Tell the server about sprint/sneak changes (vanilla ``entity_action``).

        Servers validate movement against the sprint/sneak state they have been told about, so
        emitting these before the first sprint-speed movement packet avoids false "moved too
        quickly" setbacks.
        """
        actions: list[str] = []
        if state.sneaking != self._last_sneaking:
            actions.append("start_sneaking" if state.sneaking else "stop_sneaking")
            self._last_sneaking = state.sneaking
        if state.sprinting != self._last_sprinting:
            actions.append("start_sprinting" if state.sprinting else "stop_sprinting")
            self._last_sprinting = state.sprinting
        for action in actions:
            await self._send_entity_action(action)

    async def _send_entity_action(self, action: str) -> None:
        if self.client is None:
            raise ConnectionClosed("not connected")
        await self.client.send_packet(
            "entity_action",
            {"entityId": self.entity_id or 0, "actionId": action, "jumpBoost": 0},
        )

    async def _send_position_confirmation(self, state: PlayerState) -> None:
        if self.teleport_confirm_supported:
            packet = MovementPacket("teleport_confirm", {"teleportId": self._teleport_id or 0})
        else:
            packet = self.movement.confirm(state.position, state.yaw, state.pitch, state.on_ground)
        await self._send_movement(packet)

    async def _send_movement(self, packet: MovementPacket) -> None:
        if self.client is None:
            raise ConnectionClosed("not connected")
        await self.client.send_packet(packet.name, packet.fields)

    # ------------------------------------------------------------------ events
    def event(self, coro: Callable[..., Any]) -> Callable[..., Any]:
        """Register an ``on_<event>`` handler.

        Raises:
            ValueError: When the function name does not match a catalog event.
        """
        name = getattr(coro, "__name__", "")
        try:
            event_type = event_for_name(name)
        except KeyError as exc:
            raise ValueError(f"unknown event handler {name!r}") from exc
        self.events.subscribe(event_type, coro)
        return coro

    async def wait_for(
        self,
        event: type,
        *,
        check: Callable[[Any], bool] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - public event-wait API
    ) -> Any:
        """Delegate to :meth:`EventBus.wait_for`."""
        return await self.events.wait_for(event, check=check, timeout=timeout)

    def expect(
        self,
        event: type,
        *,
        check: Callable[[Any], bool] | None = None,
        timeout: float | None = None,
    ) -> Expectation:
        """Delegate to :meth:`EventBus.expect`."""
        return self.events.expect(event, check=check, timeout=timeout)

    # ------------------------------------------------------------------ handlers
    async def _handle(self, packet: Packet) -> None:
        handler = _HANDLERS.get(packet.name)
        if handler is None:
            log.debug("unhandled play packet %s", packet.name)
            return
        await handler(self, packet)

    async def _on_join(self, packet: Packet) -> None:
        self.entity_id = int(packet.fields.get("entityId", 0))
        self.game_mode = int(packet.fields.get("gameMode", 0))
        self.dimension = int(packet.fields.get("dimension", 0))
        self.world.dimension = self.dimension
        self.joined = True
        self._join_event = JoinEvent(
            entity_id=self.entity_id,
            game_mode=self.game_mode,
            dimension=self.dimension,
            difficulty=int(packet.fields.get("difficulty", 0)),
            max_players=int(packet.fields.get("maxPlayers", 0)),
            level_type=str(packet.fields.get("levelType", "")),
        )
        self._ready.set()
        await self._send_settings()
        self.events.dispatch(self._join_event)

    async def _send_settings(self) -> None:
        if self.client is None:
            return
        await self.client.send_packet(
            "settings",
            {
                "locale": "en_US",
                "viewDistance": 2,
                "chatFlags": 0,
                "chatColors": True,
                "skinParts": 0x7F,
            },
        )

    async def _on_keep_alive(self, packet: Packet) -> None:
        if self.client is None:
            return
        await self.client.send_packet(
            "keep_alive", {"keepAliveId": int(packet.fields.get("keepAliveId", 0))}
        )

    async def _on_position(self, packet: Packet) -> None:
        fields = packet.fields
        flags = int(fields.get("flags", 0)) & 0xFF
        previous = self.physics_state.position if self.physics_state is not None else None
        if previous is None:
            previous = self.position or Vec3(0.0, 0.0, 0.0)
        x = float(fields.get("x", 0.0))
        y = float(fields.get("y", 0.0))
        z = float(fields.get("z", 0.0))
        if flags & 0x01:
            x += previous.x
        if flags & 0x02:
            y += previous.y
        if flags & 0x04:
            z += previous.z
        yaw = float(fields.get("yaw", 0.0))
        pitch = float(fields.get("pitch", 0.0))
        if flags & 0x08:
            yaw += self.yaw
        if flags & 0x10:
            pitch += self.pitch

        on_ground = self.physics_state.on_ground if self.physics_state is not None else False
        self.position = Vec3(x, y, z)
        self.yaw = yaw
        self.pitch = pitch
        # Server positions are authoritative for the pose (spawn, teleport and corrections). The
        # physics loop drives yaw/pitch from ``controls``, so mirror the server pose here; otherwise
        # the bot keeps facing its default direction (0, 0) and walks the wrong way after spawning
        # on a server that starts players at a non-zero yaw.
        self.controls = replace(self.controls, yaw=yaw, pitch=pitch)
        self.physics_state = PlayerState(self.position, yaw=yaw, pitch=pitch, on_ground=on_ground)

        # 1.9+ confirms with teleport_confirm; 1.8 has no teleport id and confirms by echoing the
        # position. Both are version-dispatched through Features rather than a protocol check here.
        self.movement.reset(self.position, yaw, pitch, on_ground)
        self._teleport_pending = True
        self._teleport_id = (
            int(fields.get("teleportId", 0)) if self.teleport_confirm_supported else None
        )

        if not self.spawned:
            self.spawned = True
            self.events.dispatch(SpawnEvent(self.position, self.yaw, self.pitch))
        self._ensure_physics_loop()

    async def _on_spawn_position(self, packet: Packet) -> None:
        location = packet.fields.get("location")
        if isinstance(location, BlockPos):
            self.spawn_position = location
        elif isinstance(location, dict) and {"x", "y", "z"} <= location.keys():
            self.spawn_position = BlockPos(
                int(location["x"]), int(location["y"]), int(location["z"])
            )

    async def _on_chat(self, packet: Packet) -> None:
        from pyflayer.bot.chat import parse_chat_json

        raw = packet.fields.get("message", "")
        position = int(packet.fields.get("position", 0))
        message = parse_chat_json(raw if isinstance(raw, str | bytes) else str(raw), position)
        self.events.dispatch(ChatEvent(message=message))

    async def _on_health(self, packet: Packet) -> None:
        self.health = float(packet.fields.get("health", self.health))
        self.food = int(packet.fields.get("food", self.food))
        self.saturation = float(packet.fields.get("foodSaturation", self.saturation))
        self.events.dispatch(HealthEvent(self.health, self.food, self.saturation))
        if self.health <= 0 and not self.dead:
            self.dead = True
            self.controls = ControlState()
            self._jump_next = False
            self.events.dispatch(DeathEvent(self.health))
            if self.auto_respawn:
                await self.respawn()

    async def _on_respawn(self, packet: Packet) -> None:
        previous = self.dimension
        self.dead = False
        self.dimension = int(packet.fields.get("dimension", self.dimension or 0))
        self.world.clear()
        self.world.dimension = self.dimension
        self.entities.clear()
        self.physics_state = None
        self.controls = ControlState()
        self.movement = MovementTracker()
        self._last_sprinting = False
        self._last_sneaking = False
        self.spawned = False
        self.events.dispatch(RespawnEvent(self.dimension))
        if previous != self.dimension:
            self.events.dispatch(DimensionChangeEvent(self.dimension, previous))

    async def _on_kick(self, packet: Packet) -> None:
        reason = ChatComponent.parse(packet.fields.get("reason", ""))
        self.kick_reason = reason
        self.events.dispatch(KickEvent(reason=reason, reason_text=reason.plain_text()))
        raise KickedError("kicked by server", reason=reason)

    async def _on_player_info(self, packet: Packet) -> None:
        action = str(packet.fields.get("action", ""))
        entries = packet.fields.get("data", [])
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            uuid = str(entry.get("uuid", ""))
            if not uuid:
                continue
            if action == "remove_player":
                removed = self.players.pop(uuid, None)
                self.events.dispatch(
                    PlayerInfoEvent(action, uuid, name=removed.name if removed else None)
                )
                continue
            info = self.players.get(uuid)
            if info is None:
                # Proxies commonly send update_* for players whose add_player we never saw (for
                # example staff hidden from the tab list). Creating a stub would pollute
                # ``bot.players`` with name-less entries, so only add_player creates entries.
                if action != "add_player":
                    log.debug("ignoring %s for unknown player %s", action, uuid)
                    continue
                info = PlayerInfo(uuid)
            if action == "add_player":
                info.name = str(entry.get("name", info.name or "")) or None
                info.game_mode = _optional_int(entry.get("gamemode"))
                info.ping = _optional_int(entry.get("ping"))
                info.display_name = _display_text(entry.get("displayName"))
            elif action == "update_game_mode":
                info.game_mode = _optional_int(entry.get("gamemode"))
            elif action == "update_latency":
                info.ping = _optional_int(entry.get("ping"))
            elif action == "update_display_name":
                info.display_name = _display_text(entry.get("displayName"))
            if action in ("add_player", "update_display_name") and (
                "displayName" not in entry or info.display_name is None
            ):
                # ``displayName`` is optional on the wire (1.8 sends it only on some servers), so
                # fall back to the tab-list name instead of leaving a misleading ``None``.
                info.display_name = info.name
            self.players[uuid] = info
            if info.name:
                self.entities.set_name(uuid, info.name)
            self.events.dispatch(
                PlayerInfoEvent(
                    action,
                    uuid,
                    name=info.name,
                    ping=info.ping,
                    game_mode=info.game_mode,
                    display_name=info.display_name,
                )
            )

    async def _on_game_state_change(self, packet: Packet) -> None:
        if packet.fields.get("reason") == "change_game_mode":
            self.game_mode = int(float(packet.fields.get("gameMode", 0)))

    # ------------------------------------------------------------------ world
    async def _on_chunk(self, packet: Packet) -> None:
        pos = ChunkPos(int(packet.fields.get("x", 0)), int(packet.fields.get("z", 0)))
        ground_up = bool(packet.fields.get("groundUp", True))
        data = decode_legacy_chunk(
            bytes(packet.fields.get("chunkData", b"")),  # type: ignore[arg-type]
            int(packet.fields.get("bitMap", 0)),
            # 1.8 sends sky light whenever the dimension has a sky, not only on ground-up chunks.
            sky_light=(self.dimension or 0) == 0,
            include_biomes=ground_up,
        )
        existing = self.world.chunks.get(pos)
        if ground_up or existing is None:
            column = ChunkColumn.from_legacy(pos, data)
        else:
            column = existing.with_legacy_update(data)
        self.world.apply_chunk(column)
        self._emit_chunk(column)

    async def _on_chunk_bulk(self, packet: Packet) -> None:
        sky_light = bool(packet.fields.get("skyLightSent", True))
        raw = memoryview(bytes(packet.fields.get("data", b"")))  # type: ignore[arg-type]
        offset = 0
        entries = packet.fields.get("meta", [])
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            bit_map = int(entry.get("bitMap", 0))
            size = bit_map.bit_count() * (4096 * 2 + 2048 + (2048 if sky_light else 0)) + 256
            data = decode_legacy_chunk(
                raw[offset : offset + size],
                bit_map,
                sky_light=sky_light,
                include_biomes=True,
                parse_block_entities=False,
            )
            offset += size
            pos = ChunkPos(int(entry.get("x", 0)), int(entry.get("z", 0)))
            column = ChunkColumn.from_legacy(pos, data)
            self.world.apply_chunk(column)
            self._emit_chunk(column)

    def _emit_chunk(self, column: ChunkColumn) -> None:
        self.events.dispatch(ChunkLoadEvent(column.pos, column.section_count, column.non_air))

    async def _on_block_change(self, packet: Packet) -> None:
        location = packet.fields.get("location")
        if not isinstance(location, dict):
            return
        pos = BlockPos(
            int(location.get("x", 0)), int(location.get("y", 0)), int(location.get("z", 0))
        )
        state_id = int(packet.fields.get("type", 0))
        old = self.world.block_state_id_or(pos, 0)
        if self.world.set_block_state(pos, state_id):
            self.events.dispatch(BlockUpdateEvent(pos, state_id, old))

    async def _on_multi_block_change(self, packet: Packet) -> None:
        chunk = ChunkPos(int(packet.fields.get("chunkX", 0)), int(packet.fields.get("chunkZ", 0)))
        records = packet.fields.get("records", [])
        if not isinstance(records, list):
            return
        changes: list[tuple[int, int, int, int]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            horizontal = int(record.get("horizontalPos", 0))
            changes.append(
                (
                    horizontal >> 4,
                    int(record.get("y", 0)),
                    horizontal & 15,
                    int(record.get("blockId", 0)),
                )
            )
        for pos, old, new in self.world.apply_multi_block_change(chunk, changes):
            self.events.dispatch(BlockUpdateEvent(pos, new, old))

    def find_blocks(
        self, matching: str | int, *, within: float = 32.0, count: int = 1
    ) -> list[BlockPos]:
        """Find nearby blocks through the world layer."""
        return self.world.find_blocks(
            matching, within=within, around=self.position or Vec3(0.0, 0.0, 0.0), count=count
        )

    # ------------------------------------------------------------------ entities
    async def _on_spawn_entity(self, packet: Packet) -> None:
        entity_id = int(packet.fields.get("entityId", 0))
        type_id = int(packet.fields.get("type", 0)) & 0xFF
        velocity = packet.fields.get("velocity")
        velocity_vector = _velocity(velocity)
        entity = self.entities.spawn(
            entity_id,
            type_id=type_id,
            position=_fixed_position(packet.fields),
            yaw=_rotation(packet.fields.get("yaw")),
            pitch=_rotation(packet.fields.get("pitch")),
            velocity=velocity_vector,
        )
        self.events.dispatch(EntitySpawnEvent(entity))

    async def _on_spawn_entity_living(self, packet: Packet) -> None:
        entity_id = int(packet.fields.get("entityId", 0))
        entity = self.entities.spawn(
            entity_id,
            type_id=int(packet.fields.get("type", 0)),
            position=_fixed_position(packet.fields),
            yaw=_rotation(packet.fields.get("yaw")),
            pitch=_rotation(packet.fields.get("pitch")),
            head_yaw=_rotation(packet.fields.get("headPitch")),
            velocity=_velocity(packet.fields.get("velocity")),
            metadata=_metadata(packet.fields.get("metadata")),
        )
        self.events.dispatch(EntitySpawnEvent(entity))

    async def _on_named_entity_spawn(self, packet: Packet) -> None:
        uuid = packet.fields.get("playerUUID")
        uuid_text = str(uuid) if uuid is not None else None
        entity = self.entities.spawn(
            int(packet.fields.get("entityId", 0)),
            type_id=54,
            type_name="player",
            uuid=uuid_text,
            position=_fixed_position(packet.fields),
            yaw=_rotation(packet.fields.get("yaw")),
            pitch=_rotation(packet.fields.get("pitch")),
            metadata=_metadata(packet.fields.get("metadata")),
        )
        if uuid_text:
            info = self.players.get(uuid_text)
            if info is not None and info.name:
                entity.name = info.name
        self.events.dispatch(EntitySpawnEvent(entity))

    async def _on_entity_move(self, packet: Packet) -> None:
        entity = self.entities.move_relative(
            int(packet.fields.get("entityId", 0)),
            int(packet.fields.get("dX", 0)),
            int(packet.fields.get("dY", 0)),
            int(packet.fields.get("dZ", 0)),
            on_ground=bool(packet.fields.get("onGround", False)),
        )
        if entity is not None:
            self.events.dispatch(EntityMoveEvent(entity))

    async def _on_entity_look(self, packet: Packet) -> None:
        entity = self.entities.look(
            int(packet.fields.get("entityId", 0)),
            int(packet.fields.get("yaw", 0)),
            int(packet.fields.get("pitch", 0)),
            on_ground=bool(packet.fields.get("onGround", False)),
        )
        if entity is not None:
            self.events.dispatch(EntityMoveEvent(entity))

    async def _on_entity_move_look(self, packet: Packet) -> None:
        entity = self.entities.move_look(
            int(packet.fields.get("entityId", 0)),
            int(packet.fields.get("dX", 0)),
            int(packet.fields.get("dY", 0)),
            int(packet.fields.get("dZ", 0)),
            int(packet.fields.get("yaw", 0)),
            int(packet.fields.get("pitch", 0)),
            on_ground=bool(packet.fields.get("onGround", False)),
        )
        if entity is not None:
            self.events.dispatch(EntityMoveEvent(entity))

    async def _on_entity_teleport(self, packet: Packet) -> None:
        entity = self.entities.teleport(
            int(packet.fields.get("entityId", 0)),
            _fixed_position(packet.fields),
            yaw=int(packet.fields.get("yaw", 0)),
            pitch=int(packet.fields.get("pitch", 0)),
            on_ground=bool(packet.fields.get("onGround", False)),
        )
        if entity is not None:
            self.events.dispatch(EntityMoveEvent(entity))

    async def _on_entity_destroy(self, packet: Packet) -> None:
        ids = packet.fields.get("entityIds", [])
        if isinstance(ids, list) and ids:
            for entity in self.entities.remove_many([int(value) for value in ids]):
                self.events.dispatch(EntityGoneEvent(entity))

    async def _on_entity_metadata(self, packet: Packet) -> None:
        metadata = _metadata(packet.fields.get("metadata"))
        entity = self.entities.set_metadata(int(packet.fields.get("entityId", 0)), metadata)
        if entity is not None:
            self.events.dispatch(EntityMetadataEvent(entity.entity_id, dict(entity.metadata)))

    async def _on_entity_equipment(self, packet: Packet) -> None:
        item = packet.fields.get("item")
        if isinstance(item, ItemStack):
            self.entities.set_equipment(
                int(packet.fields.get("entityId", 0)), int(packet.fields.get("slot", 0)), item
            )

    async def _on_entity_head_rotation(self, packet: Packet) -> None:
        self.entities.set_head_yaw(
            int(packet.fields.get("entityId", 0)), int(packet.fields.get("headYaw", 0))
        )

    async def _on_entity_velocity(self, packet: Packet) -> None:
        velocity = packet.fields.get("velocity")
        if isinstance(velocity, dict):
            entity = self.entities.set_velocity(
                int(packet.fields.get("entityId", 0)),
                (
                    int(velocity.get("x", 0)),
                    int(velocity.get("y", 0)),
                    int(velocity.get("z", 0)),
                ),
            )
            if entity is not None:
                self.events.dispatch(EntityMoveEvent(entity))

    async def _on_attach_entity(self, packet: Packet) -> None:
        self.entities.attach(
            int(packet.fields.get("entityId", 0)),
            int(packet.fields.get("vehicleId", 0)),
            leash=bool(packet.fields.get("leash", False)),
        )

    # ------------------------------------------------------------------ inventory
    async def _on_window_items(self, packet: Packet) -> None:
        window_id = int(packet.fields.get("windowId", 0))
        items = packet.fields.get("items", [])
        if not isinstance(items, list):
            return
        self.inventory.apply_window_items(
            window_id, [item if isinstance(item, ItemStack) else ItemStack() for item in items]
        )
        self.events.dispatch(InventoryChangedEvent(window_id, -1, None))

    async def _on_set_slot(self, packet: Packet) -> None:
        window_id = int(packet.fields.get("windowId", 0))
        slot = int(packet.fields.get("slot", 0))
        item = packet.fields.get("item")
        stack = item if isinstance(item, ItemStack) else ItemStack()
        if self.inventory.apply_set_slot(window_id, slot, stack) is not None:
            event_slot = CURSOR_EVENT_SLOT if slot == CURSOR_SLOT else slot
            self.events.dispatch(InventoryChangedEvent(window_id, event_slot, stack))

    async def _on_held_item_slot(self, packet: Packet) -> None:
        # 1.8 names this field ``slotId``; older fixtures used ``slot``. Accept both so a server
        # hotbar change is never silently ignored.
        slot = int(packet.fields.get("slotId", packet.fields.get("slot", 0)))
        self.inventory.set_held_slot(slot)
        self.events.dispatch(
            InventoryChangedEvent(
                0, HOTBAR_START + self.inventory.held_slot, self.inventory.held_item
            )
        )

    async def _on_open_window(self, packet: Packet) -> None:
        window_id = int(packet.fields.get("windowId", 0))
        title = ChatComponent.parse(packet.fields.get("windowTitle", "")).plain_text()
        self.inventory.open_window(
            window_id,
            title,
            int(packet.fields.get("slotCount", 0)),
            kind=str(packet.fields.get("inventoryType", "")),
        )

    async def _on_close_window(self, packet: Packet) -> None:
        if self.inventory.close_window(int(packet.fields.get("windowId", 0))) is not None:
            # The cursor belongs to the closed window; the server returns it to the inventory and
            # sends new slot contents. Keeping the old cursor would double-count it locally.
            self.inventory.cursor = ItemStack()

    async def _on_experience(self, packet: Packet) -> None:
        self.experience = (
            float(packet.fields.get("experienceBar", 0.0)),
            int(packet.fields.get("level", 0)),
            int(packet.fields.get("totalExperience", 0)),
        )
        self.events.dispatch(ExperienceEvent(*self.experience))

    async def _on_attributes(self, packet: Packet) -> None:
        if int(packet.fields.get("entityId", 0)) != self.entity_id:
            return
        properties = packet.fields.get("properties", [])
        if not isinstance(properties, list):
            return
        for prop in properties:
            if isinstance(prop, dict) and "key" in prop:
                self.attributes[str(prop["key"])] = float(prop.get("value", 0.0))

    def __repr__(self) -> str:
        return f"Bot(username={self.username!r}, host={self.host!r}, connected={self.connected})"


def _optional_int(value: object) -> int | None:
    """Coerce a decoded numeric field, tolerating mappers that already produced an int."""
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _display_text(value: object) -> str | None:
    """Flatten a 1.8 ``displayName`` (plain string or JSON chat component) to text."""
    if value is None:
        return None
    if isinstance(value, ChatComponent):
        return value.plain_text() or None
    if isinstance(value, str):
        text = ChatComponent.parse(value).plain_text()
        return text or None
    if isinstance(value, (dict, list)):
        return ChatComponent.parse(value).plain_text() or None
    return str(value) or None


def _fixed_position(fields: dict[str, Any]) -> Vec3:
    """1.8 fixed-point entity position (1/32 block)."""
    return Vec3(
        int(fields.get("x", 0)) / 32.0,
        int(fields.get("y", 0)) / 32.0,
        int(fields.get("z", 0)) / 32.0,
    )


def _rotation(value: object) -> float:
    """1.8 rotation byte (1/256 turn) to degrees."""
    return int(value or 0) * 360.0 / 256.0


def _velocity(value: object) -> Vec3:
    """1.8 velocity (1/8000 block per tick) to blocks per tick."""
    if not isinstance(value, dict):
        return Vec3(0.0, 0.0, 0.0)
    return Vec3(
        int(value.get("x", 0)) / 8000.0,
        int(value.get("y", 0)) / 8000.0,
        int(value.get("z", 0)) / 8000.0,
    )


def _metadata(value: object) -> dict[int, Any]:
    if not isinstance(value, dict):
        return {}
    return {int(key): item for key, item in value.items()}


_HANDLERS: dict[str, Callable[[Bot, Packet], Awaitable[None]]] = {
    "login": Bot._on_join,
    "keep_alive": Bot._on_keep_alive,
    "position": Bot._on_position,
    "spawn_position": Bot._on_spawn_position,
    "chat": Bot._on_chat,
    "update_health": Bot._on_health,
    "respawn": Bot._on_respawn,
    "kick_disconnect": Bot._on_kick,
    "player_info": Bot._on_player_info,
    "game_state_change": Bot._on_game_state_change,
    "map_chunk": Bot._on_chunk,
    "map_chunk_bulk": Bot._on_chunk_bulk,
    "block_change": Bot._on_block_change,
    "multi_block_change": Bot._on_multi_block_change,
    "spawn_entity": Bot._on_spawn_entity,
    "spawn_entity_living": Bot._on_spawn_entity_living,
    "named_entity_spawn": Bot._on_named_entity_spawn,
    "rel_entity_move": Bot._on_entity_move,
    "entity_look": Bot._on_entity_look,
    "entity_move_look": Bot._on_entity_move_look,
    "entity_teleport": Bot._on_entity_teleport,
    "entity_destroy": Bot._on_entity_destroy,
    "entity_metadata": Bot._on_entity_metadata,
    "entity_equipment": Bot._on_entity_equipment,
    "entity_head_rotation": Bot._on_entity_head_rotation,
    "entity_velocity": Bot._on_entity_velocity,
    "attach_entity": Bot._on_attach_entity,
    "window_items": Bot._on_window_items,
    "set_slot": Bot._on_set_slot,
    "held_item_slot": Bot._on_held_item_slot,
    "open_window": Bot._on_open_window,
    "close_window": Bot._on_close_window,
    "experience": Bot._on_experience,
    "update_attributes": Bot._on_attributes,
}
