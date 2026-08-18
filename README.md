# GameRuntimeMcpHost

[한국어 README](README.ko.md)

A dependency-free Model Context Protocol (MCP) stdio host that exposes an explicit set of token-authenticated localhost game runtime commands to compatible AI clients.

```text
MCP client
  -> stdio
  -> GameRuntimeMcpHost
  -> 127.0.0.1 RPC + per-session token
  -> game-owned runtime adapter
```

The host owns transport only. Legal actions, turn validation, authorization, and authoritative state mutation remain in the game adapter.

## Requirements

- Python 3.10 or newer
- An MCP-compatible client
- A game runtime adapter that writes a session descriptor and accepts the declared RPC contract

The runtime and the host must run on the same machine.

## Install

```powershell
git clone https://github.com/lLcrowe/GameRuntimeMcpHost.git
cd GameRuntimeMcpHost
python -m pip install -e .
```

Verify the installation:

```powershell
game-runtime-mcp-host --help
python -m unittest discover -s tests -v
```

## Quick start

Start a runtime adapter first, then provide its session descriptor and a tool manifest:

```powershell
game-runtime-mcp-host `
  --session-file C:\path\to\runtime-session.json `
  --tools-file C:\path\to\tools.json
```

For a runtime that writes discoverable sessions under `LocalLow`, the host can start before the game and reconnect after Play Mode or process restarts:

```powershell
game-runtime-mcp-host `
  --session-name llm-conversation-lab-runtime-mcp.json `
  --session-product LLMConversationLab `
  --tools-file examples/llm-conversation-runtime.tools.json
```

## MCP client configuration

The exact configuration file depends on the client. A generic stdio registration looks like this:

```json
{
  "mcpServers": {
    "game_runtime": {
      "command": "python",
      "args": [
        "-X",
        "utf8",
        "C:/path/to/GameRuntimeMcpHost/src/game_runtime_mcp_host.py",
        "--session-name",
        "llm-conversation-lab-runtime-mcp.json",
        "--session-product",
        "LLMConversationLab",
        "--tools-file",
        "C:/path/to/GameRuntimeMcpHost/examples/llm-conversation-runtime.tools.json"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

Codex CLI can register the same process directly:

```powershell
codex mcp add game_runtime `
  --env PYTHONIOENCODING=utf-8 `
  --env PYTHONUTF8=1 `
  -- python -X utf8 C:\path\to\GameRuntimeMcpHost\src\game_runtime_mcp_host.py `
  --session-name llm-conversation-lab-runtime-mcp.json `
  --session-product LLMConversationLab `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\llm-conversation-runtime.tools.json
```

Restart or open a new client session after changing MCP registration.

## Session descriptor

The game-owned adapter writes a JSON file with this contract:

```json
{
  "protocolVersion": 1,
  "endpoint": "http://127.0.0.1:18761/",
  "token": "per-session-secret",
  "tokenHeader": "X-Game-Runtime-Token",
  "rpcPath": "/rpc",
  "product": "ExampleGame",
  "processId": 1234
}
```

The endpoint must use a numeric loopback address. The token is never included in logs or MCP responses.

## Tool manifest

The tool manifest maps MCP tool names to game-owned RPC commands and JSON schemas. Start from one of these examples:

| Manifest | Purpose |
|---|---|
| [`tools.example.json`](examples/tools.example.json) | Minimal generic contract |
| [`storyllmmaster.tools.json`](examples/storyllmmaster.tools.json) | External game-master control surface |
| [`llm-conversation-runtime.tools.json`](examples/llm-conversation-runtime.tools.json) | Multi-participant conversation runtime |

`clientName` is observational metadata, not an authorization mechanism. Conversation participant tools use a participant token issued by `join_conversation` in addition to the runtime session token kept by the host.

## Environment variables

| Variable | Equivalent option |
|---|---|
| `GAME_RUNTIME_MCP_SESSION` | `--session-file` |
| `GAME_RUNTIME_MCP_SESSION_NAME` | `--session-name` |
| `GAME_RUNTIME_MCP_SESSION_PRODUCT` | `--session-product` |
| `GAME_RUNTIME_MCP_TOOLS` | `--tools-file` |

Command-line values take precedence over their environment defaults.

## Troubleshooting

| Symptom | Check |
|---|---|
| Tools do not appear | Validate the manifest JSON, restart the MCP client, and confirm the registered command path. |
| No runtime session is found | Start the game, verify `--session-name` and `--session-product`, or pass `--session-file` explicitly. |
| Connection refused | Confirm the runtime adapter is listening and that the descriptor points to its current port. |
| Endpoint is rejected | Use a numeric loopback address such as `127.0.0.1` or `::1`; remote hosts are intentionally blocked. |
| Unauthorized response | Restart the game or retry the next call so the host reloads the latest session token. |
| Korean text is corrupted | Launch Python with `-X utf8` and set `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`. |

## Scope and limitations

- Included: MCP initialize, ping, tool listing/calls, localhost RPC, token forwarding, bounded timeout, and session rediscovery.
- Excluded: arbitrary C# execution, remote binding, game-file access, provider SDK calls, and game-rule validation.
- Adapter responsibility: legal-action validation, idempotency, timeout fallback, and authoritative state mutation.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes. Report security issues according to [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
