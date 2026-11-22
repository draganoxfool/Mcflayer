<div align="center">

# ⛏️ mcflayer

### Asyncio library for Minecraft Java Edition bots

mcflayer provides protocol, world, physics, action, command, and multi-bot APIs. Its documented
reference target is Minecraft 1.8.9 (protocol 47); this does not imply support for every protocol
version represented in the vendored data.

[![PyPI](https://img.shields.io/badge/pypi-mcflayer-blue?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/mcflayer/)
[![Python](https://img.shields.io/badge/python-3.11+-yellow?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Minecraft](https://img.shields.io/badge/minecraft-1.8.9-green?style=for-the-badge)](#)
[![Protocol](https://img.shields.io/badge/protocol-47-orange?style=for-the-badge)](#)
[![Docs](https://img.shields.io/badge/docs-MkDocs_Material-purple?style=for-the-badge)](#documentation)

Install the `mcflayer` distribution and import `pyflayer`.

</div>

---

## Features

| | |
|---|---|
| **Transport and authentication** | Connection, framing, encryption, status, and authentication components |
| **World state** | Chunk, block, entity, and inventory models for the implemented reference target |
| **Physics and actions** | Physics tick driver, collision, pathfinding, and scheduled bot actions |
| **Commands and tasks** | discord.py-inspired commands, cogs, extensions, and scheduled tasks |
| **Swarm** | Multi-bot clusters, shared chunk storage, login staggering, coordination, and metrics |
| **Verification** | Unit, golden, and loopback tests; live validation remains subject to roadmap gates |

---

## 🗺️ Roadmap

Reference target: **Minecraft 1.8.9 / protocol 47**. The vendored `minecraft-data` files are a
subset and do not, by themselves, indicate protocol or feature support.

| Milestone | Scope | Status |
|:---:|---|:---:|
| **M1–M3** | Transport, bot core, and world state | Implemented; see roadmap for verification status |
| **M4–M5** | Physics, movement, commands, and tasks | Implemented |
| **M6** | Pathfinding and actions | Implemented; roadmap validation gates remain outstanding |
| **M7** | Swarm and shared worlds | Implemented; live soak deferred |
| **Gate** | Live vanilla/Paper anti-cheat soak | Environment-dependent |

📓 Dig deeper: [Session log](docs/sessions.md) · [Task board](docs/tasks.md)

---

## 📦 Install

```bash
pip install mcflayer
```

The PyPI distribution is **`mcflayer`**; the import package is **`pyflayer`**:
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
examples/       🎯 runnable demos, including M4 physics, M5 commands and M7 swarm
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
