# Bug Review and Fix Status

Read-only review of the current code. Findings below describe defects and recommended fixes; application code was not changed. The 1.8.9 vanilla-server checks used an isolated, offline-mode Docker container on localhost port 25566. The existing listener on port 25565 was left untouched.

## Confirmed Bugs

### 1. Compression opt-out breaks login

**Severity:** High  
**Status:** Fixed and covered by `tests/test_client.py`.  
**Location:** `src/pyflayer/protocol/client.py`, `_login_loop()` (`compress` handling)

When `use_compression=False`, the client ignores the server's `Set Compression` packet. Compression is a server-directed framing change, not a capability the client can safely decline after the server sends it. The next frame is decoded using the old framing, so login stalls or fails. Against vanilla 1.8.9, the default configuration connected and read the `login` packet; `use_compression=False` timed out during login.

**How to fix:** Always apply the received threshold before reading the next packet. Remove `use_compression` as a negotiation switch, or redefine it so it cannot make the client ignore a mandatory server framing change.

**Regression test:** Have a server send `Set Compression`, connect with both values of the option, and verify login plus a subsequent compressed packet. The real vanilla probe already demonstrates the failure case.

### 2. Legacy chunk data incorrectly infers block entities from trailing bytes

**Severity:** High  
**Status:** Fixed and covered by `tests/test_chunk_world.py` and `tests/test_bot_world.py`.  
**Location:** `src/pyflayer/protocol/native/chunk_data.py`, `decode_legacy_chunk()`; `src/pyflayer/bot/bot.py`, `_on_tile_entity_data()`

The 1.8.9 `map_chunk.chunkData` payload contains the declared chunk sections and, for ground-up chunks, biome bytes; block entities are not appended as NBT roots. They arrive independently in clientbound `tile_entity_data` packets (packet ID `0x35`) with a packed location, action, and optional NBT. Parsing trailing bytes as consecutive NBT compounds can therefore create phantom entities or consume unrelated bytes, while ignoring the separate packet loses real block entities.

**How to fix:** Preserve all bytes after the declared chunk layout without interpreting them. Handle `tile_entity_data` separately by storing its dict payload at the decoded packet location when that chunk is loaded; ignore missing chunks and null NBT (there is no protocol action for removal).

**Regression tests:** `test_chunk_world.py` verifies NBT-looking and arbitrary chunk tails remain untouched and do not populate `block_entities`. `test_bot_world.py` sends an encoded `tile_entity_data` packet and verifies `world.block_entity_at()` returns its NBT payload.

### 3. Container `slotCount` is treated as total window size

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_bot.py` and `tests/test_inventory.py`.  
**Location:** `src/pyflayer/bot/bot.py`, `_on_open_window()`; `src/pyflayer/bot/inventory.py`, `open_window()`

The 1.8 `open_window.slotCount` field is the number of container slots, excluding the player's 36-slot inventory copy. `_on_open_window()` passes that count directly to a `Window` whose size represents all slots. Until `window_items` arrives and replaces the list, the copied player slots do not exist; intermediate `set_slot` updates are dropped and clicks can use an empty item value. Existing tests manually add 36 before opening, so they do not exercise the wire handler contract.

**How to fix:** For ordinary container windows, allocate the container count plus the 36 player-inventory slots. Keep special window types such as the horse inventory aligned with their protocol-specific layout.

**Regression test:** Feed an `open_window` packet with a chest `slotCount` of 27, then apply a player-copy `set_slot` update before `window_items`; verify the resulting window has 63 slots and retains the update.

### 4. Rejected inventory transactions are not acknowledged

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_bot.py`.  
**Location:** `src/pyflayer/bot/bot.py`, packet handler table

The 1.8 protocol defines the clientbound and serverbound `transaction` packets, but the bot has no handler for the server's rejected-click confirmation. Vanilla clients acknowledge the transaction. Without that response, the server can keep the window interaction blocked until the client acknowledges/resynchronizes, preventing later clicks from working normally.

**How to fix:** Handle clientbound `transaction` packets and send the required serverbound acknowledgement with the same window and action identifiers and the accepted state required by the 1.8 protocol.

**Regression test:** Simulate a rejected transaction, assert the bot sends the matching acknowledgement, and verify a later window click can proceed.

### 5. Large movement deltas tunnel through collision boxes

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_physics.py`.  
**Location:** `src/pyflayer/physics/collision.py`, `_clip_axis()`

Collision candidates are selected from the box translated to the final position, rather than the full swept region between the start and end. A direct probe moved a player box three blocks through a stone wall: it ended beyond the wall with `hit_z=False`. Large impulses or other unusually large per-tick deltas can therefore pass through terrain.

**How to fix:** Enumerate collision shapes across the full swept AABB and clamp the axis movement to the closest obstacle encountered in the direction of travel.

**Regression test:** Move a box through a wall by more than one block in one call; assert it stops at the wall and reports a collision. Include both movement directions and thin shapes.

### 6. Sneaking does not hold the player at a ledge

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_physics.py` and `tests/test_physics_oracle.py`.  
**Location:** `src/pyflayer/physics/engine.py`, movement input and collision call

Sneak input only scales movement speed. There is no grounded edge-support clamp before movement. A direct 40-tick probe on a platform ending at Z=10 moved a sneaking player from Z=8.5 to Z=10.83 and left `on_ground=False`. Vanilla 1.8 sneak movement prevents walking off a ledge while grounded.

**How to fix:** Apply vanilla's sneak edge-clipping rule to horizontal motion while grounded, reducing the attempted displacement until the player AABB remains supported.

**Regression test:** Walk toward each platform edge while sneaking, including diagonal movement; assert the player stops at the edge and remains grounded.

### 7. Fluid sampling misses partial AABB overlap

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_physics.py` and `tests/test_physics_oracle.py`.  
**Location:** `src/pyflayer/physics/media.py`, `sample_medium()`

The sampler checks only the floored center X/Z column at three heights. It misses a fluid block that overlaps the player's hitbox but does not contain the center. A direct probe at X=1.02, with the player AABB overlapping water in block X=0, returned `in_water=False`. Fluid drag and movement behavior therefore begin late when entering water from the side.

**How to fix:** Test the player's relevant bounding volume against fluid blocks and their fluid surface height, rather than sampling only the center column.

**Regression test:** Move into water until the hitbox partially overlaps the block while the center remains outside; assert the fluid state and drag begin at the expected boundary.

### 8. Breaking an event-stream loop leaves its listener registered

**Severity:** Medium  
**Status:** Fixed with an async context-manager lifecycle and covered by `tests/test_events.py`.  
**Location:** `src/pyflayer/events/bus.py`, `_EventStream.__anext__()` and `aclose()`

The stream subscribes on its first `__anext__()` and unsubscribes only when `aclose()` is called. Breaking out of `async for` does not automatically call `aclose()` on an arbitrary asynchronous iterator. A direct probe that retained the stream after breaking showed one live subscription remained. It continues receiving events and can retain callback/state references.

**How to fix:** Give the stream an explicit async context-manager lifecycle and document/use it, or return an async generator whose `finally` reliably unsubscribes. Do not claim arbitrary `async for` cleanup is automatic.

**Regression test:** Break after one event while retaining the stream, then assert the bus has no live subscription for that stream and subsequent events are not queued.

### 9. NBT strings do not use Java Modified UTF-8

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_nbt.py` with Java-compatible vectors.  
**Location:** `src/pyflayer/protocol/types/nbt.py`, `_read_string()` and `_Writer.string()`

NBT strings are encoded/decoded as standard UTF-8. Java's NBT I/O uses `DataInput`/`DataOutput` UTF string encoding (Modified UTF-8), which differs for NUL and supplementary Unicode characters. Such NBT values can be rejected or decoded differently, and writing them can produce bytes a Java server interprets incorrectly. The module documents this limitation, but that does not make the wire behavior interoperable for those valid values.

**How to fix:** Implement Java Modified UTF-8 for NBT string payloads and names, enforcing the unsigned-short encoded-byte limit. Keep Minecraft protocol strings on their separately specified encoding.

**Regression test:** Compare NBT string vectors containing NUL and supplementary characters against Java `DataOutput.writeUTF`/`DataInput.readUTF`, in both directions.

### 10. Restarting a finite task loop does not reset its iteration count

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_commands.py`.  
**Location:** `src/pyflayer/ext/tasks/loop.py`, `_BoundLoop.start()`, `restart()`, and `_run()`

`_current_loop` is initialized once and incremented until `count` is reached. `restart()` calls `start()` without resetting it. After a `count=1` loop completes, restarting sees `_current_loop >= count` and exits without another callback invocation.

**How to fix:** Reset per-run iteration state at the start of a new run while keeping any desired lifetime statistics separate.

**Regression test:** Start a `count=1` loop, await completion, restart it, and verify the callback runs once in each run.

### 11. Concurrent command calls can pass the limit while `before_invoke` awaits

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_commands.py`.  
**Location:** `src/pyflayer/ext/commands/core.py`, `can_run()` and `invoke()`

The concurrency check runs before invocation, but the non-waiting running count is incremented only after the awaited `before_invoke` hook. Two concurrent calls can both pass the check, suspend in that hook, then both increment and execute despite `max_concurrency(1)`. With `wait=True`, hook work also occurs before acquiring the semaphore.

**How to fix:** Reserve the concurrency slot before any awaited hook that belongs to the invocation, and release it in a `finally` path for hook failures, callback failures, cancellation, and success. Keep queueing semantics explicit for `wait=True`.

**Regression test:** Use a yielding `before_invoke` hook and two simultaneous calls; assert the configured limit is never exceeded and that waiting calls acquire/release in order.

### 12. Variadic command arguments are passed as one nested list

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_commands.py`.  
**Location:** `src/pyflayer/ext/commands/core.py`, `_consume()` and `invoke()`

For a callback declared `async def collect(ctx, *words)`, `_consume()` appends all tokens as one list to `ctx.args`, and `invoke()` expands only the outer argument list. The callback receives `words == (['one', 'two'],)` rather than `('one', 'two')`.

**How to fix:** Store variadic values in a representation that `invoke()` expands into individual positional arguments, without changing greedy-parameter semantics.

**Regression test:** Invoke a `*words` command with multiple tokens and assert the callback receives one positional argument per token.

### 13. Failed cog setup can leave cog registrations behind

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_commands.py`.  
**Location:** `src/pyflayer/ext/commands/bot.py`, `add_cog()` and `_rollback()`

`add_cog()` registers the cog, commands, and listeners, then awaits `cog_load()`. It adds the cog to the active extension rollback ledger only after that await succeeds. If `cog_load()` raises while an extension is loading, rollback cannot find the partially registered cog, leaving it and its listeners registered after the extension fails.

**How to fix:** Add the cog to the rollback ledger before awaiting `cog_load()`, or explicitly undo every registration when the hook raises.

**Regression test:** Load an extension whose cog registers a command and listener and raises from `cog_load()`; assert the cog, command, subscriptions, and loops are all removed.

### 14. Bare non-boolean flags are accepted as `True`

**Severity:** Medium  
**Status:** Fixed and covered by `tests/test_commands.py`.  
**Location:** `src/pyflayer/ext/commands/flags.py`, `FlagConverter.convert()`

When a flag has no following value, `raw is None` unconditionally assigns `True`, regardless of the annotated type. Thus `--count` for `count: int` succeeds with a `bool` value and can silently corrupt downstream command logic.

**How to fix:** Permit a valueless flag only when its annotation/converter is boolean; otherwise raise `BadArgument` for the missing value.

**Regression test:** Assert `--silent` works for `bool`, while bare `--count` for `int` raises `BadArgument`; retain support for `--count=5` and `--count 5`.

### 15. Task-loop `reconnect` option has no effect

**Severity:** Medium  
**Status:** Fixed and covered by reconnect lifecycle tests in `tests/test_commands.py`.  
**Location:** `src/pyflayer/ext/tasks/loop.py`, `Loop.__init__()` and `_BoundLoop._run()`

The public option is documented as pausing and resuming a loop when the connection is lost and is stored as `self.reconnect`, but there are no reads of that attribute anywhere in the implementation. A loop configured with either `reconnect=True` or `False` behaves identically; tick-based loops can wait on events from a disconnected session and do not implement the documented lifecycle behavior.

**How to fix:** Integrate the option with bot connection/disconnection lifecycle events: pause/cancel the current wait on disconnect and resume according to the configured value after reconnect. If that behavior is not supported, remove or explicitly deprecate the option and correct the docstring rather than silently accepting it.

**Regression test:** Run a loop on a bot, disconnect and reconnect, and assert the documented pause/resume behavior for both option values, including tick-based loops.

### 16. Disabled commands are still invoked

**Severity:** Low  
**Status:** Fixed and covered by `tests/test_commands.py`.  
**Location:** `src/pyflayer/ext/commands/core.py`, `Command.enabled`; `src/pyflayer/ext/commands/bot.py`, `dispatch_command()`

The command constructor and decorator expose `enabled=False`, and `Command` stores that value, but dispatch never checks it before preparing or invoking the command. A disabled command remains available through chat and executes normally, so callers cannot use this public option to shut off a command.

**How to fix:** Reject or skip disabled commands at a clearly defined dispatch boundary, using the library's established error-handling behavior. If the option is not intended to control invocation, remove it or document its actual meaning.

**Regression test:** Register a command with `enabled=False`, dispatch it through normal chat parsing and direct dispatch, and verify its callback does not run; verify the enabled form still runs.

## Real-Server Test Notes

- A disposable vanilla 1.8.9 server accepted the default client configuration and the client read a `login` packet.
- The same server caused `use_compression=False` to time out during login, confirming finding 1.
- The host's existing listener on port 25565 was not used or changed; Docker ran the test server on 127.0.0.1:25566 in offline mode.
- The physics, event-stream, and NBT issues were reproduced with direct local probes; regression coverage has since been added with the fixes.
- Direct probes also confirmed the task restart, variadic argument, max-concurrency, and bare-flag findings; the loop callback ran only once across two runs, varargs arrived nested, two limited bodies overlapped, and a bare integer flag became `True`.
- All listed findings have fixes and regression coverage. Vanilla 1.8.9 was used to verify compression negotiation; the block-entity correction was checked against the protocol-47 packet definitions and vanilla packet implementation.
