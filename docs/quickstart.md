# Quickstart

Install `mcflayer` and connect a bot to a Minecraft Java server. The current reference target is
Java Edition 1.8.9 (protocol 47); newer protocol support is incomplete.

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

`--timeout` is the number of seconds to remain connected after joining. A leading `/` in `--chat`
sends a server command rather than public chat.

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

`bot.connect()` returns after Join Game. Spawn position and tab-list updates arrive while
`bot.run()` reads packets. Wait for `SpawnEvent` before relying on `bot.position`.

## Next steps

- [Bot guide](modules/bot.md): connection, state, chat and movement.
- [Commands](modules/commands.md): command dispatch, cogs and checks.
- [Events](modules/events.md): waiters, streams and event types.
- [API reference](reference/index.md): public signatures.
- Repository `examples/`: runnable physics, commands and server examples.
