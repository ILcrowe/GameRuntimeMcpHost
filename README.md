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

The runtime and host must run on the same machine.

## Install

```powershell
git clone https://github.com/ILcrowe/GameRuntimeMcpHost.git
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

## Unity C# adapter sample

The repository includes a copy-ready Unity adapter, optional generic diagnostics, a companion manifest, and a PlayMode round-trip test:

- [`examples/unity/README.md`](examples/unity/README.md) — setup, scene placement, extension, and security boundaries
- [`UnityRuntimeMcpSampleBridge.cs`](examples/unity/Runtime/UnityRuntimeMcpSampleBridge.cs) — loopback listener, session descriptor, bounded main-thread dispatch
- [`UnityRuntimeDiagnosticsProvider.cs`](examples/unity/Runtime/UnityRuntimeDiagnosticsProvider.cs) — optional build identity, incremental logs, metrics, and screenshot capture
- [`unity-runtime-sample.tools.json`](examples/unity/unity-runtime-sample.tools.json) — runtime status, diagnostics, and main-thread echo

The sample components are explicit `MonoBehaviour`s; they do not install a hidden runtime bootstrap or a second transport.

## Unity gameplay sample

[`examples/unity-gameplay/README.md`](examples/unity-gameplay/README.md) is a registered gameplay sample for observing and controlling a running Unity Player through explicit tools:

```text
runtime_status
get_game_state
get_surroundings
player_move_to
player_interact
send_in_game_chat
```

It uses the current host `protocol` / `command` / `payload` request contract and includes actual sample Transform movement, bounded nearby interaction, and a game-owned chat event. It is an alternative to `examples/unity`; do not enable both bridges in the same runtime path.

## Optional runtime diagnostics

[`RUNTIME_DIAGNOSTICS.md`](RUNTIME_DIAGNOSTICS.md) defines a small game-independent observation surface:

| MCP tool | Purpose |
|---|---|
| `runtime_status` | Runtime/process liveness and identity |
| `runtime_build_info` | Build/version identity |
| `runtime_logs_read` | Bounded incremental logs |
| `runtime_metrics_snapshot` | One bounded performance snapshot |
| `runtime_capture_screenshot` | One adapter-controlled visual capture |

These tools do not replace game-specific commands. Runtime arbitrary-code execution is intentionally excluded from the baseline.

## Agent skill

A low-reasoning operating skill is included under [`skills/game-runtime-mcp-host`](skills/game-runtime-mcp-host). It fixes the task order to:

```text
target gate
  -> runtime status
  -> build identity when relevant
  -> exact game-owned command
  -> result/state verification
  -> optional diagnostics
```

The Unity gameplay sample procedure is documented in [`unity-gameplay-sample.md`](skills/game-runtime-mcp-host/references/unity-gameplay-sample.md).

Install it project-locally for Codex with:

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

See [`skills/README.md`](skills/README.md) for manual installation and boundaries. MCP registration provides callable tools; the skill provides routing, retry, and verification procedure.

## External Agent session adapters

Version 0.3 also provides reusable, CLI-backed Provider session adapters:

- `CodexPersistentSession` — one Codex app-server process, one persistent primary thread, isolated utility threads
- `GrokHeadlessSession` — bounded `grok -p` calls with structured output and native `--resume` persistence
- `JsonRpcStdioClient`, `ProviderSessionDescriptor`, and `AppendOnlyConversationStream` — provider-neutral process/session primitives

The consuming game still owns prompts, JSON Schemas, conversation rules, and authoritative state mutation. These modules own Provider process transport and native session continuity only. See [`EXTERNAL_AGENT_SESSIONS.md`](EXTERNAL_AGENT_SESSIONS.md).

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

Open a new client session after changing MCP registration or project-local skills.

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

## Tool manifests

A tool manifest maps MCP tool names to game-owned RPC commands and JSON Schemas.

| Manifest | Purpose |
|---|---|
| [`tools.example.json`](examples/tools.example.json) | Minimal generic contract |
| [`runtime-diagnostics.tools.json`](examples/runtime-diagnostics.tools.json) | Optional generic runtime diagnostics contract |
| [`unity-runtime-sample.tools.json`](examples/unity/unity-runtime-sample.tools.json) | Copy-ready Unity C# diagnostics adapter sample |
| [`game-runtime.tools.json`](examples/unity-gameplay/game-runtime.tools.json) | Unity state, movement, interaction, and chat sample |
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
| `GAME_RUNTIME_GROK_SOURCE_HOME` | Source Grok home used only to copy cached authentication into an isolated runtime home |

Command-line values take precedence over environment defaults.

## Troubleshooting

| Symptom | Check |
|---|---|
| Tools do not appear | Validate the manifest JSON, restart the MCP client, and confirm the registered command path. |
| No runtime session is found | Start the game, verify `--session-name` and `--session-product`, or pass `--session-file` explicitly. |
| Connection refused | Confirm the runtime adapter is listening and that the descriptor points to its current port. |
| Endpoint is rejected | Use a numeric loopback address such as `127.0.0.1` or `::1`; remote hosts are intentionally blocked. |
| Unauthorized response | Restart the game or retry a read-only call so the host reloads the latest session token. |
| Diagnostics are unavailable | Attach and enable `UnityRuntimeDiagnosticsProvider`, or remove unpublished diagnostics from the manifest. |
| Gameplay tools are unavailable | Confirm that `GameRuntimeMcpBridge` and `SampleGamePlayActionHandler` are enabled and that the gameplay manifest is selected. |
| Korean text is corrupted | Launch Python with `-X utf8` and set `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`. |
| Grok inherits personal MCP configuration | Use `GrokHeadlessSession`; it creates an isolated per-scope `GROK_HOME` and copies only cached authentication. |

## Scope and limitations

- Included: MCP initialize, ping, tool listing/calls, localhost RPC, token forwarding, bounded timeout, session rediscovery, optional runtime diagnostics examples, a Unity gameplay example, and CLI-backed external-agent session transport
- Excluded: arbitrary C# execution, remote binding, game-file access, provider SDK calls, game-specific prompt construction, and game-rule validation
- Adapter responsibility: legal-action validation, idempotency, timeout fallback, authoritative state mutation, and save/run scope selection

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes. Report security issues according to [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
