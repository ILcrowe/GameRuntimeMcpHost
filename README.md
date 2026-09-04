# GameRuntimeMcpHost

[한국어 README](README.ko.md)

Dependency-free MCP stdio host for explicit, token-authenticated localhost game runtime commands.

```text
MCP client
  -> stdio
  -> GameRuntimeMcpHost
  -> 127.0.0.1 HTTP RPC + per-session token
  -> game-owned runtime adapter
```

The host owns transport. The game adapter owns legal-action validation, authorization, and authoritative state mutation.

## Requirements

- Python 3.10+
- MCP-compatible client
- Game runtime adapter that publishes a session descriptor and handles the RPC contract
- Host and runtime on the same machine

## Install

```powershell
git clone https://github.com/ILcrowe/GameRuntimeMcpHost.git
cd GameRuntimeMcpHost
python -m pip install -e .

game-runtime-mcp-host --help
python -m unittest discover -s tests -v
```

## Quick start

```powershell
game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file examples\unity\game-runtime.tools.json
```

The host may start before the game. The next tool call rediscovers a recreated runtime session.

## Unified Unity sample

```text
examples/unity/
├─ Runtime/
│  ├─ GameRuntimeMcpBridge.cs
│  ├─ SampleGameRuntimeHandler.cs
│  └─ SampleRuntimeMcpInteractable.cs
├─ Tests/
│  └─ GameRuntimeMcpTests.cs
└─ game-runtime.tools.json
```

- `GameRuntimeMcpBridge`: session, token, listener, main-thread queue, command registry, diagnostics
- `SampleGameRuntimeHandler`: state, surroundings, movement, interaction, chat
- `SampleRuntimeMcpInteractable`: Inspector-attachable interaction sample
- `game-runtime.tools.json`: MCP schemas and Unity RPC command mappings
- `GameRuntimeMcpTests`: PlayMode round-trip coverage

Guide: [`examples/unity/README.md`](examples/unity/README.md)

## Runtime tools

Diagnostics:

```text
runtime_status
runtime_build_info
runtime_logs_read
runtime_metrics_snapshot
runtime_capture_screenshot
```

Gameplay:

```text
get_game_state
get_surroundings
player_move_to
player_interact
send_in_game_chat
```

Runtime arbitrary-code execution is intentionally excluded.

## Agent skill

Project-local Codex install:

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

Fixed low-reasoning order:

```text
target gate
-> runtime status
-> build identity when relevant
-> exact game-owned tool
-> result/state verification
-> optional diagnostics
```

## External agent sessions

Version 0.3 includes:

- `CodexPersistentSession`
- `GrokHeadlessSession`
- `JsonRpcStdioClient`
- `ProviderSessionDescriptor`
- `AppendOnlyConversationStream`

The consuming game owns prompts, JSON Schemas, conversation rules, and authoritative mutation. Shared modules own provider process transport and native session continuity.

Details: [`EXTERNAL_AGENT_SESSIONS.md`](EXTERNAL_AGENT_SESSIONS.md)

## MCP registration

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
        "game-runtime-mcp-session.json",
        "--session-product",
        "UnityGameRuntime",
        "--tools-file",
        "C:/path/to/GameRuntimeMcpHost/examples/unity/game-runtime.tools.json"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

Open a new client session after changing MCP registration or project-local skills.

## Session descriptor

```json
{
  "protocolVersion": 1,
  "endpoint": "http://127.0.0.1:18765/",
  "token": "per-session-secret",
  "tokenHeader": "X-Game-Runtime-Token",
  "rpcPath": "/rpc",
  "product": "UnityGameRuntime",
  "processId": 1234
}
```

Numeric loopback endpoints only. Tokens never belong in logs or MCP responses.

## Tool manifests

| Manifest | Purpose |
|---|---|
| `examples/tools.example.json` | Minimal generic contract |
| `examples/runtime-diagnostics.tools.json` | Diagnostics-only contract |
| `examples/unity/game-runtime.tools.json` | Unified Unity diagnostics and gameplay sample |
| `examples/storyllmmaster.tools.json` | External game-master control surface |
| `examples/llm-conversation-runtime.tools.json` | Multi-participant conversation runtime |

## Environment variables

| Variable | Option |
|---|---|
| `GAME_RUNTIME_MCP_SESSION` | `--session-file` |
| `GAME_RUNTIME_MCP_SESSION_NAME` | `--session-name` |
| `GAME_RUNTIME_MCP_SESSION_PRODUCT` | `--session-product` |
| `GAME_RUNTIME_MCP_TOOLS` | `--tools-file` |
| `GAME_RUNTIME_GROK_SOURCE_HOME` | Authentication source for isolated Grok homes |

Command-line values take precedence.

## Scope

Included:

```text
MCP initialize / ping / tools
localhost RPC
token forwarding
bounded timeout
session rediscovery
Unity sample
runtime diagnostics
provider session transport
```

Excluded:

```text
arbitrary runtime C#
remote binding
game-file access
provider SDK calls
game-specific prompts
game-rule validation
```

## Contributing and security

- [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [`SECURITY.md`](SECURITY.md)
- MIT license
