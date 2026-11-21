<div align="center">

# ⛏️ mcflayer

### Mineflayer's brain. discord.py's soul. Pure asyncio.

**An asyncio Minecraft Java Edition bot library that speaks fluent protocol and commands like a Discord bot.**

[![PyPI](https://img.shields.io/badge/pypi-mcflayer-blue?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/mcflayer/)
[![Python](https://img.shields.io/badge/python-3.10+-yellow?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Minecraft](https://img.shields.io/badge/minecraft-1.8.9-green?style=for-the-badge)](#)
[![Protocol](https://img.shields.io/badge/protocol-47-orange?style=for-the-badge)](#)
[![Docs](https://img.shields.io/badge/docs-MkDocs_Material-purple?style=for-the-badge)](#documentation)

`pip install mcflayer` → `import pyflayer`

</div>

---

## ✨ Why mcflayer?

You know **Mineflayer**: battle-tested protocol, world and physics.
You know **discord.py**: the cleanest command framework around.

**mcflayer fuses them.** Write Minecraft bots the way you write Discord bots: cogs, converters, checks, flags, auto-generated help, hot-reloadable extensions. All on `asyncio`, fully typed.

```python
# the vibe (see examples/ for runnable demos)
@bot.command()
async def follow(ctx, player: Player):
    ...
```

---

## 🚀 Features

| | |
|---|---|
| 🔌 **Transport & Auth** | Login, encryption, and a clean event system |
| 🌍 **World Awareness** | Chunks, blocks, entities, inventory |
| 🏃 **Deterministic Physics** | Drift-compensated **20 TPS** loop, vanilla movement-packet cadence, sprint/sneak `entity_action`, teleport confirmation |
| 🎮 **Command Layer** | No prefix needed. Cogs, converters, checks, flags, help, **atomic extension reload**, and `tasks.loop` locked to physics ticks |
| 🧪 **Tested** | Unit, golden, and loopback tests, plus live verification on PikaNetwork |

---

## 🗺️ Roadmap

Built against **Minecraft 1.8.9 / protocol 47**.

| Milestone | Scope | Status |
|:---:|---|:---:|
| **M1** | Transport, login/auth | ✅ Live-verified on PikaNetwork |
| **M2** | Events, bot core | ✅ Live-verified |
| **M3** | Chunks, blocks, entities, inventory | ✅ Live-verified |
| **M4** | Physics and movement | ✅ Implemented |
| **M5** | Commands and tasks | ✅ Implemented |
| **Gate** | 10-minute anti-cheat soak on live vanilla/Paper | 🔜 Environment-dependent |
| **M6** | Pathfinding | 🛠️ Planned |
| **M7** | Swarm | 🛠️ Planned |

📓 Dig deeper: [Session log](docs/sessions.md) · [Task board](docs/tasks.md)

---

## 📦 Install

```bash
pip install mcflayer
```

> 💡 **Heads up:** the PyPI distribution is **`mcflayer`** (the `pyflayer` name was taken), but the import stays **`pyflayer`**:
> ```python
> import pyflayer
> ```

---

## ⚡ Quick Start

```bash
# 1. Set up your environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]

# 2. Ping a server
python -m pyflayer.protocol.status play.example.org

# 3. Join, read chat, say hi
python -m pyflayer.cli play.pika-network.net --username Steve --timeout 15 --chat hello

# 4. Run the tests
pytest
```

---

## 🗂️ Project Layout

```
src/pyflayer/   🧠 library code (src layout, fully typed)
data/pc/1.8/    📚 vendored subset of PrismarineJS/minecraft-data (MIT)
tests/          🧪 unit, golden and loopback tests
docs/           📖 MkDocs site: architecture, roadmap, prompts, modules, sessions, tasks
examples/       🎯 runnable demos, including M4 physics and M5 commands
```

---

## 📖 Documentation

Built with **MkDocs (Material theme)**.

```bash
pip install -r requirements-docs.txt
mkdocs serve
```

Read the Docs builds the same site from `.readthedocs.yaml`.

---

<div align="center">

**Built with ⛏️ and ☕ · Licensed data courtesy of [PrismarineJS/minecraft-data](https://github.com/PrismarineJS/minecraft-data) (MIT)**

</div>
