# Missing Features & Future Ideas

This document outlines features that are **not yet implemented** in pyflayer but could be added to make the library more useful for bot operators, automation enthusiasts, and anyone who wants to run semi-afk or fully-afk Minecraft bot setups. The target audience is people who like bots and automation — people who want to set up farms, AFK farms, mini-game grinders, and general purpose bots that handle routine tasks.

The project currently focuses on 1.8.9/protocol-47, so many of these features would need protocol extensions for modern Minecraft versions. However, even within 1.8.9 scope, there are many useful additions.

---

## ### Automation Macros & Recorded Sequences

### Problem
There's no way to record a sequence of actions (clicks, chats, item uses) and replay them. This is essential for AFK farms, automated PvP, and repetitive grinds.

### Proposed API
```python
# Record a macro while you play manually
bot.start_macro_recording()  # starts capturing window clicks, chats, item uses
bot.stop_macro_recording()  # stops and saves the macro

# Replay the macro
bot.replay_macro("macros/bed_break.py")  # replays a recorded bed-breaking sequence

# Parameterized macro replay
bot.replay_macro("macros/chest_open.py", count=28)  # open chest 28 times

# Macro with hooks
bot.replay_macro("macros/craft_table.py", on_step=lambda n: print(f"step {n}"))
```

### Design Notes
- Would capture `click_slot`, `use_item`, `place_block`, `chat` events
- Could store as JSON with timestamps
- Useful for: BedWars bed rushes, cobblestone generators, automatic farms
- Should respect rate limiting to avoid "moved too quickly" kicks

---

## ### Inventory Filtering & Sorting

### Problem
No way to filter items in a container or sort inventory contents. In BedWars, you might want to quickly extract only beds or only diamonds from a chest.

### Proposed API
```python
# Filter: get all slots containing a specific item type
slots = bot.filter_window(window_id, item_id="minecraft:bed")

# Sort a container's slots (shifts clicks to sort by item type)
bot.sort_window(window_id)  # sorts container slots

# Filter player inventory
player_slots = bot.filter_inventory(item_id="minecraft:coal")

# Sort all inventory (player + containers)
bot.sort_all()

# Remove all of a specific item type
bot.remove_from_inventory(item_id="minecraft:dirt", count=64)
```

### Use Cases
- **BedWars**: Extract only beds from a mixed chest, keep swords separate
- **Farm bots**: Sort crops from seeds, harvest only ready crops
- **Resource gathering**: Filter iron from gold from diamond in mined chunks
- **Trash management**: Remove junk items to free inventory space

### Design Notes
- Leverages existing `Window.container_slots` and slot indexing
- Could use `shift_click_slot` to move items to/from chest storage
- Should work for all container types (chest, furnace, brewing stand, etc.)

---

## ### Entity & Combat Automation

### Problem
No high-level combat automation: targeting, attack cycling, enchanted tool usage, or PvP patterns.

### Proposed API
```python
# Attack the nearest entity in range
bot.attack_nearest(range=32)

# Attack a specific entity by name/UUID
bot.attack_entity(uuid="uuid-here")

# Auto-attack loop with interval
bot.start_attack_loop(interval=0.5)  # attacks every 0.5s
bot.stop_attack_loop()

# Use best available weapon on target
bot.use_best_weapon(target_entity)

# Toggle PvP mode (critical hits, no critical hits)
bot.set_pvp_mode("critical")
bot.set_pvp_mode("normal")
```

### Design Notes
- Would use `bot.entities` tracking + raycasting to find targets
- Could integrate with the physics engine for swing timing
- 1.8 combat: axe cooldown, sword sweep, critical hit ground detection
- Useful for: PvP arenas, mob grinders, automatic enemy killing

---

## ### Chat Command Automation

### Problem
No way to auto-respond to chat commands or listen for specific patterns.

### Proposed API
```python
# Listen for a command and auto-respond
@bot.event
async def on_chat(event: ChatEvent):
    if event.message.content.startswith("/hello"):
        await bot.chat("hi there!")


# Filter commands by prefix
bot.listen_for_command("/heal", response="/heal accepted")
bot.listen_for_command("/time", response="/time is " + str(bot.world.time))

# Keyword-based responses
bot.wait_for_keyword("help", timeout=10.0)  # resolves when "help" appears
bot.respond_to("where are you", "/pos")
```

### Use Cases
- **Automod**: Auto-kick or auto-warn for rule violations
- **Bot coordination**: "Who has beds?" -> bot responds with its bed status
- **AFK status**: "Is anyone on?" -> bot replies with position
- **Mini-game control**: "start", "stop", "restart" commands

### Design Notes
- Builds on existing `ChatEvent` and `on_chat`
- Should have configurable cooldowns to prevent spam
- Could integrate with `bot.chat()` rate limiting

---

## ### Potion & Effect Management

### Problem
No API to brew potions, apply effects, or check effect durations.

### Proposed API
```python
# Brew a potion with specified effects
bot.brew_potion(
    output_slot,
    ingredients=["minecraft:nether_wart", "minecraft:blaze_powder"],
    effects=[
        {"type": "minecraft:strength", "duration": 200, "amplifier": 1},
        {"type": "minecraft:speed", "duration": 180, "amplifier": 0},
    ],
    secondary=False,  # no redstone/glowstone
)

# Check if bot has a potion effect
has_effect = bot.has_effect("minecraft:night_vision")

# Remove a potion effect
bot.remove_effect("minecraft:invisibility")

# Give self a potion effect instantly
bot.add_effect("minecraft:fire_resistance", duration=600, amplifier=0)

# Splash potion throwing
bot.throw_splash_potion("minecraft:healing", position=target_pos, duration=600)
```

### Use Cases
- **PvP bots**: Auto-before combat with speed/strength
- **Farm bots**: Night vision for night-time farming
- **Combat bots**: Auto-regeneration with regeneration potions
- **Breeding**: Instant growth with growth potions

### Design Notes
- 1.8 potion brewing protocol: water bottles, nether wart, primary/secondary ingredients
- Effect durations: 1.8 has fixed durations per amplifier level
- Could integrate with brewing stand windows (`Window.container_slots` ~4 for brewing stand)

---

## ### Villager Trading Automation

### Problem
No way to automate villager trades, restock, or trade-specific items.

### Proposed API
```python
# Trade with a villager (click the trade slot)
bot.trade_villager(villager_entity, trade_slot)  # clicks the specific trade

# Restock villager supplies
bot.restock_villager(villager_entity)  # performs restocking trades

# Buy all available trades
bot.buy_all_trades(villager_entity)  # clicks all unlocked trades

# Sell items to villager (if they buy)
bot.sell_to_villager(villager_entity, item_id="minecraft:emerald", count=64)

# Find villager with specific trade
villager = bot.find_villager(has_trade_for="minecraft:diamond")
```

### Use Cases
- **Economy bots**: Buy low, sell high across villager villages
- **Resource farms**: Trade paper/books for emeralds, then buy tools
- **Enchanting alt**: Trade for enchanted books
- **Mob farm sell**: Sell mob drops to villagers

### Design Notes
- Villager has ~6-7 trades at each level
- Restocking uses `entity_equipment` and `set_slot` packets
- Trading uses `click_slot` on the villager window (type 50 = villager)
- Should check villager `profession` and `level` before trading

---

## ### Anvil Operations

### Problem
No API to use anvors: rename items, combine enchantments, repair items.

### Proposed API
```python
# Rename an item
bot.rename_anvil(item, new_name="Sharpness V Sword")

# Combine two items (keep enchantments from both)
bot.combine_anvil(item_a, item_b)

# Repair item with matching material
bot.repair_anvil(item, material="minecraft:iron_ingot")  # uses ingots as currency

# Rename + repair combined
bot.rename_and_repair_anvil(item, new_name="Sharpness V Sword", repair_with="minecraft:iron_ingot")
```

### Use Cases
- **PvP gear**: Combine enchanted books with swords
- **Tool maintenance**: Repair diamond pickaxes with iron/diamonds
- **Name tags**: Name your pets/mobs
- **Enchant alt**: Combine low-level enchants into high-level

### Design Notes
- Anvil window type: 7 (type 7 = anvil)
- Costs experience levels + material costs
- Would need to track XP levels before/after
- Uses `click_slot` on anvil window slots

---

## ### Beacon Activation

### Problem
No API to set up and activate beacons with pyramid levels.

### Proposed API
```python
# Set the beacon primary power
bot.set_beacon_power(
    beacon_pos,
    primary_effect="minecraft:speed",  # speed, haste, jump, etc.
    pyramid_level=4,  # 1-4, requires proper pyramid
)

# Check beacon status
is_active, effect = bot.beacon_status(beacon_pos)

# Quick pyramid check
bot.check_pyramid(pos, required_level=4)
```

### Use Cases
- **Speed/haste bases**: Auto-activate beacon powers
- **Status effect bots**: Maintain specific effects while AFK
- **Base marking**: Beacons as base landmarks

### Design Notes
- Beacon window type: 81 (type 81 = beacon)
- Pyramid requirements: level 1 = 3x3, level 2 = 5x5, level 3 = 7x7, level 4 = 9x9
- Primary/secondary powers can be set
- Requires beacon block placed on valid top block

---

## ### Elytra & Flight Automation

### Problem
No API to manage elytra flight, landing, or height maintenance.

### Proposed API
```python
# Check if bot has elytra equipped
has_elytra = bot.has_elytra_equipped()

# Auto-land at specific Y level
bot.auto_land(target_y=64, speed=1.0)

# Rise to a specific height
bot.rise_to_height(target_y=128, speed=0.5)

# Check flight status
is_flying = bot.is_flying()

# Toggle creative/flying (if permissions allow)
bot.set_creative_mode(True)
bot.set_survival_mode()
```

### Use Cases
- **Sky block bots**: Fly between islands
- **Map art bots**: Aerial photography
- **PvP escape**: Quick elytra getaway
- **End farming**: Fly back from the End

### Design Notes
- 1.8: Elytra is off-hand slot, flying uses double-jump
- Requires firework rockets for sustained flight
- Would integrate with physics engine for flight pathing
- Height maintenance: avoid falling while looking around

---

## ### Totem & Off-Hand Management

### Problem
No API to manage off-hand items (totems of undying, shields, building blocks).

### Proposed API
```python
# Check off-hand status
off_hand = bot.off_hand_slot()  # returns slot index or None

# Equip item to off-hand from hotbar
bot.to_off_hand(hotbar_slot)

# Equip item to main hand from off-hand
bot.to_main_hand()

# Use off-hand item (totem, shield block)
bot.use_off_hand()  # click/use the off-hand item

# Check if totem is active (recently used)
recent_totem_use = bot.totem_cooldown_remaining()

# Force off-hand use (useful for macros)
bot.force_off_hand_use()
```

### Use Cases
- **Totem snatching**: Auto-equip totem when low health
- **Shield block**: Auto-block projectiles
- **Building blocks**: Keep building block in off-hand for rapid placement
- **Item switching**: Swap between building block and tool

### Design Notes
- 1.8 protocol: off-hand is slot 40+ (hotbar index 8+)
- Totem of undying: triggers when health would drop to 0
- Shield: right-click use blocks projectiles
- Off-hand slots are separate from hotbar (30-35 in 1.8)

---

## ### Server Query & Status

### Problem
No way to query server MOTD, version, player count, or latency without connecting.

### Proposed API
```python
# Quick server status without full connection
status = bot.query_server("play.pika-network.net")
# Returns: motd, version, players_on, players_max, latency

# Ping the server
ping = bot.ping_server("play.pika-network.net")
# Returns: response time in ms

# Check if server is online
is_online = bot.is_server_online("play.pika-network.net")
```

### Use Cases
- **Bot launcher**: Only connect if server is up
- **Monitoring**: Display server status in bot dashboard
- **Failover**: Switch between multiple server IPs
- **Scheduled bots**: Only run when server is online

### Design Notes
- Uses SLP (Server List Ping) protocol
- Non-intrusive: doesn't connect to Play, just status request
- Could use `pyflayer.protocol.status` primitives

---

## ### Reconnection & Resume Strategies

### Problem
No built-in support for graceful reconnect + resume from where you left off.

### Proposed API
```python
# Bot with automatic reconnect + state resume
bot = Bot(
    "Steve",
    host="play.pika-network.net",
    reconnect=True,
    resume_state=True,  # try to restore inventory, position, etc.
)

# On reconnect, attempt to rejoin previous game
await bot.resume_after_reconnect()

# Save current state for later resume
state = bot.save_state()  # inventory, position, XP, etc.

# Load saved state
bot.load_state(state)  # restore inventory, teleport, etc.
```

### Design Notes
- Could save: hotbar contents, inventory, position, XP, level, gamemode
- On reconnect: rejoin same server, restore inventory via window clicks
- Useful for: Long-running bots, crash recovery, network blips
- Would need to handle inventory differences on rejoin

---

## ### Multi-Bot Coordination

### Problem
No API for multiple bots to coordinate (share resources, avoid conflicts, divide tasks).

### Proposed API
```python
# Simple coordination: divide tasks among N bots
coordinator = bot.coordinator(task_count=4)  # 4 bots working together

# Assign each bot a task
bot.set_task("mine")  # bot mines
bot.set_task("farm")  # bot farms
bot.set_task("craft")  # bot crafts
bot.set_task("trade")  # bot trades

# Check if task is assigned to this bot
my_task = bot.my_task()  # returns "mine", "farm", etc.

# Avoid conflicts on shared resources
bot.claim_chunk((0, 0))  # claims chunk, returns True if successful
bot.release_chunk((0, 0))  # releases claim

# Share information across bots
broadcast = bot.broadcast("found_diamonds_at_10_20")
# Other bots: bot.received_broadcast("found_diamonds_at_10_20")
```

### Use Cases
- **Massive farms**: 4 bots each handle different farm type
- **Resource distribution**: Each bot handles different resource type
- **PvP teams**: Coordinated attacks
- **Server capacity**: Distribute load across multiple bots

### Design Notes
- Could use file-based locking or Redis for persistence
- Per-bot state should be isolated
- Useful for: VPS hosting multiple bots, large-scale automation

---

## ### Performance Monitoring

### Problem
No way to monitor bot performance: TPS, memory, packet rates, loop stalls.

### Proposed API
```python
# Current TPS
tps = bot.current_tps()  # e.g., 20.0

# Memory usage
mem = bot.memory_usage()  # returns {rss: ..., vms: ..., python: ...}

# Loop stall detection
stalls = bot.loop_stalls()  # count of stalled ticks

# Packet rate monitoring
packet_rate = bot.packet_rate()  # packets per second

# Set performance alerts
bot.set_tps_alert(15.0)  # alert if TPS drops below 15
bot.set_memory_alert(256)  # alert if memory > 256 MB

# Performance summary
summary = bot.performance_summary()
# Returns dict with tps, mem, stalls, packet_rate, uptime
```

### Use Cases
- **VPS hosting**: Monitor multiple bots on limited resources
- **Crash detection**: TPS drop often precedes disconnection
- **Optimization**: Identify bottlenecks in bot code
- **Uptime tracking**: Report bot health to dashboard

### Design Notes
- TPS measured over last 100 ticks
- Memory via `tracemalloc` or `psutil`
- Useful for: Production bots, VPS management, reliability

---

## ### Farm Automation Helpers

### Problem
No high-level farming automation: crop growth detection, animal breeding, mob farming.

### Proposed API
```python
# Detect ready crops in range
ready_crops = bot.detect_crops(range=32)  # returns slot positions

# Harvest all crops in area
bot.harvest_crops(range=32)  # clicks on ready crops

# Check crop growth stage
stage = bot.crop_stage(block_pos)  # 0=planted, 7=fully_grown

# Breed animals in range
bot.breed_animals(range=32, animal="cow")  # feeds two cows, returns baby

# Kill mobs in area (for mob farms)
bot.clear_mobs(range=32, mob_types=["zombie", "skeleton"])

# Plant crops
bot.plant_crops(range=32, crop_type="wheat")
```

### Use Cases
- **Crop farms**: Automatic harvest when ready
- **Animal farms**: Breeding and population management
- **Mob farms**: Clear spawns, keep spawner active
- **Mixed farms**: Combine crop + animal + mob clearing

### Design Notes
- Crop detection: raycast or block below player feet
- Animal breeding: needs two same-type animals + food
- Mob clearing: use swords/axes, or area-of-effect attacks
- Would integrate with `bot.world` block states

---

## ### Anvil + Enchanting Automation

### Problem
No API to combine enchanting automation: enchant table + anvil chain.

### Proposed API
```python
# Enchant an item at enchant table
bot.enchant_item(enchant_table_window, item_slot, level_target=5)  # tries for level 5

# Rename after enchant
bot.rename_after_enchant(item, new_name="My Sword")

# Combine enchants via anvil
bot.anvil_chain(
    [
        {"item": "sword", "enchant": "sharpness"},
        {"item": "book", "enchant": "unbreaking"},
    ],
    target_name="Ultimate Sword",
)

# Check enchantability
is_enchantable = bot.is_enchantable(enchant_table_window, item_slot)
```

### Use Cases
- **PvP gear**: Full sharpness V diamond sword
- **Tool optimization**: Efficiency V + Fortune V pickaxe
- **Book farming**: Specific enchant combinations
- **Cost minimization**: XP-efficient enchanting

### Design Notes
- Enchant table window type: 53
- XP cost depends on level, item, and anvil usage
- Would need to track XP levels before/after
- Can be expensive: high-level enchants cost significant XP

---

## ### Brewing Stand Automation

### Problem
No API to automate brewing stands: ingredient addition, progress monitoring, output collection.

### Proposed API
```python
# Start brewing with ingredients
bot.brew_stand_start(
    stand_window,
    ingredients=[
        "minecraft:nether_wart",  # always needed
        "minecraft:blaze_powder",  # fuel
        "minecraft:nether_stalk",  # primary ingredient
        "minecraft:sugar",  # secondary
    ],
)

# Check brewing progress
progress = bot.brewing_progress(stand_window)  # 0.0 to 1.0

# Take output items
bot.take_brewing_output(stand_window)  # clicks output slots

# Check if brewing is complete
is_done = bot.is_brewing_done(stand_window)

# Force stop brewing
bot.stop_brewing(stand_window)
```

### Use Cases
- **Potion farms**: Mass potion production
- **Effect management**: Brew specific potions on demand
- **Resource production**: Regular nether wart/honey/meal farming

### Design Notes
- Brewing stand window type: 54
- Brewing time: 20 ticks per ingredient (10 seconds per step)
- 3 input slots + 1 output slot + 1 fuel slot
- Fuel: blaze powder lasts 1 brew, lava bucket lasts 20 brews

---

## ### Existing Already (Reference)

The following already exist and are documented in the codebase:

| Feature | Module | Since |
|---|---|---|
| `click_slot()` | `bot/windows.py` | M5 |
| `shift_click_slot()` | `bot/windows.py` | M5 |
| `use_item()` | `bot/interactions.py` | M5 |
| `place_block()` | `bot/interactions.py` | M5 |
| `break_block()` | `bot/interactions.py` | M5 |
| `Window.container_slots` | `bot/inventory.py` | M5 |
| `Window.kind` | `bot/inventory.py` | M5 |
| `select_hotbar()` | `bot/windows.py` | M5 |

These are the "built-in" features. Everything below is **missing / would-be-nice** for automation enthusiasts.

---

## ### Prioritization Matrix

| Priority | Feature Category | Key Features | Effort Estimate | Impact on Audience |
|---|---|---|---|---|
| **High** | Inventory Automation | `move_to_container`, `filter_window`, `sort_window`, `move_all` | Medium | **Very high** — any bot needs inventory management |
| **High** | Clicking & Macros | `auto_click`, `replay_macro`, `wait_click` | Medium-High | **High** — core for AFK, BedWars, grinds |
| **High** | Combat/AI | `attack_nearest`, `start_attack_loop`, `use_best_weapon` | Medium | **High** — PvP, mob grinders, defense |
| **Medium** | Resource Management | `brew_potion`, `enchant_item`, `trade_villager`, `repair_anvil` | Medium | **High** — progression, gear, economy |
| **Medium** | Farming | `detect_crops`, `harvest_crops`, `breed_animals`, `clear_mobs` | Medium-High | **Medium-High** — food, resources, mob farms |
| **Medium** | Window Ops | `filter_window`, `sort_window`, `remember_window`, `restore_window` | Low-Medium | **Medium** — reusable across bots |
| **Low** | Navigation | `goto_bed`, `goto_base`, `return_to_spawn` | High (needs pathfinder) | **Low-Medium** — depends on M6 |
| **Low** | Effects & Stats | `has_effect`, `add_effect`, `current_tps`, `memory_usage` | Low | **Medium** — monitoring & convenience |
| **Low** | Off-Hand | `to_off_hand`, `to_main_hand`, `use_off_hand` | Low | **Low-Medium** | niche but useful |
| **Low** | Server Query | `query_server`, `ping_server`, `is_server_online` | Low | **Low** | convenience only |
| **Low** | Coordination | `coordinator`, `claim_chunk`, `broadcast` | Medium | **Low** | multi-bot setups only |

---

## ### Getting Started for Automation Enthusiasts

If you're reading this because you want to automate Minecraft, here's the recommended path:

1. **Start with the built-in features** — `click_slot`, `shift_click_slot`, `use_item`, `place_block`, `break_block` — these cover 80% of automation needs

2. **Add inventory helpers** — `filter_window`, `sort_window`, `move_to_container` — these make inventory management painless

3. **Try macros** — record bed-breaking sequences or chest-clicking patterns for AFK play

4. **Explore the missing features** that match your use case:
   - BedWars? → `auto_click`, `break_all_beds`, `move_to_container`
   - Crop farm? → `detect_crops`, `harvest_crops`, `plant_crops`
   - PvP bot? → `attack_nearest`, `start_attack_loop`, `use_best_weapon`
   - Economy? → `trade_villager`, `enchant_item`, `repair_anvil`

5. **Combine with the existing API** — the `Bot` class, `EventBus`, `PhysicsEngine`, and `World` state give you everything needed to build on top of these foundations

6. **Check the roadmap** — M6 (pathfinder) and M7 (swarm) will add navigation capabilities that complement these automation features

---

## ### Calling for Contributions

Many of these features are modular and could be contributed back to pyflayer. If you implement any of the above, consider:

- Adding the functions to `bot/windows.py` or `bot/interactions.py`
- Writing tests for the new functionality
- Updating `docs/reference/bot.md` with the new API
- Submitting a PR with the new modules and documentation

The project's scope is 1.8.9/protocol-47, but many of these features translate to modern versions with protocol adjustments. Even within 1.8.9, there's significant room for automation improvement.

---

*Last updated: alongside pyflayer 0.8.1 release*
*Target audience: bot operators, automation enthusiasts, AFK farm developers, Minecraft bot community*