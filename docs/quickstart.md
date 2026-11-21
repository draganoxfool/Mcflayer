# Quickstart

Install the package and join a Minecraft Java server in a few lines.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install mcflayer        # import name: pyflayer
```

## Ping a server

```bash
python -m pyflayer.protocol.status play.example.org
```

## Join and print chat

```bash
python -m pyflayer.cli play.pika-network.net --username Steve --timeout 15 --chat hello
```

`--timeout` is the number of seconds to stay connected after joining. A leading `/` in `--chat`
sends a command instead of public chat.

## Run a bot

```python
import asyncio

from pyflayer import Bot
from pyflayer.events import ChatEvent, SpawnEvent


async def main() -> None:
    bot = Bot("Steve", host="play.pika-network.net", version="1.8.9")

    @bot.event
    async def on_spawn(event: SpawnEvent) -> None:
        print(f"spawned at {event.position}")

    @bot.event
    async def on_chat(event: ChatEvent) -> None:
        print(f"<{event.message.sender}> {event.message.content}")

    await bot.connect()
    await bot.run()


asyncio.run(main())
```

`bot.connect()` returns after Join Game; spawn position and tab-list packets arrive while
`bot.run()` is reading. Use `bot.wait_for(SpawnEvent)` or the `on_spawn` handler before relying on
`bot.position`.

## Next steps

- [Bot guide](modules/bot.md) — state, chat, movement and PikaNetwork notes.
- [Commands](modules/commands.md) — address-based dispatch, cogs and checks.
- [Events](modules/events.md) — waiters, streams and the event catalog.
- [API reference](reference/index.md) — exact signatures for every public module.
- `examples/` in the repository — runnable physics, commands and PikaNetwork demos.
