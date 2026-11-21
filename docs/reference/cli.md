# `pyflayer.cli`

Command-line interface entry points for connecting to a Minecraft server.

## `pyflayer-connect`

Connect to a Minecraft server, optionally send one message, then stay connected for a fixed time.

```bash
pyflayer-connect play.pika-network.net --username Steve --timeout 15 --chat "hello"
pyflayer-connect play.pika-network.net -u Steve --timeout 15 --chat "/register password password"
```

**Positional arguments**

| Argument | Meaning |
|---|---|
| `host` | Server hostname or IP |

**Named arguments**

| Argument | Meaning | Default |
|---|---|---|
| `--username`, `-u` | Offline-mode username | Required |
| `--port` | Server port | `25565` |
| `--version` | Minecraft version | `1.8.9` |
| `--timeout` | Seconds to stay connected after joining | `30` |
| `--chat` | Message or command to send after joining | — |
| `--no-srv` | Skip the SRV lookup | off |
| `--reconnect` | Reconnect with exponential backoff | off |
| `--verbose`, `-v` | Debug logging | off |

`--timeout` is **not** a join timeout: it is how long the process stays connected after Join Game.
A leading `/` in `--chat` sends a command (`bot.send_command()`); otherwise the text is sent as
public chat through `bot.chat()`, which strips leading slashes as a safety measure.

## `python -m pyflayer.cli`

Equivalent to `pyflayer-connect`.

```bash
python -m pyflayer.cli play.pika-network.net -u Steve --timeout 15
```

The same arguments are accepted.

## Quick example

```bash
pyflayer-connect play.pika-network.net --username Steve --chat "hello world"
```

This connects, waits for Join Game, sends the message, prints chat and spawn events, stays for 30
seconds, then disconnects.

## Under the hood

The CLI is a thin wrapper around `pyflayer.Bot`. It closes the bot and the event bus in a `finally`
block even when connect, chat, or the read loop fails.

```python
import asyncio
import pyflayer

bot = pyflayer.Bot("Steve", host="play.pika-network.net")
await bot.connect()
await bot.chat("hello")
await bot.run()
```
