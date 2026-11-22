# Command-line entry points

The installed console scripts are declared in `pyproject.toml`:

| Script | Target | Purpose |
|---|---|---|
| `pyflayer-connect` | `pyflayer.cli:main` | Connect a bot to a server |
| `pyflayer-status` | `pyflayer.protocol.status:main` | Query server status |

`pyflayer-connect` accepts a host, required `--username`/`-u`, `--port`, `--version`, `--timeout`,
`--chat`, `--no-srv`, `--reconnect`, and `--verbose`/`-v` options. Its timeout bounds the connected
run after joining. Use `pyflayer-connect --help` for the installed parser's exact usage.

| Option | Default |
|---|---|
| `--username`, `-u` | Required |
| `--port` | `25565` |
| `--version` | `1.8.9` |
| `--timeout` | `30.0` seconds |
| `--chat` | Not set |
| `--no-srv` | `false` |
| `--reconnect` | `false` |
| `--verbose`, `-v` | `false` |

The connect CLI is also available as a module:

```bash
python -m pyflayer.cli HOST --username NAME
```

The status command is also available as a module:

```bash
python -m pyflayer.protocol.status HOST
```

::: pyflayer.cli.main

::: pyflayer.protocol.status.main
