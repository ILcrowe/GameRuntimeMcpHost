# Unity gameplay runtime MCP sample

[한국어 가이드](README.ko.md)

This copy-ready sample lets an MCP client observe and play a running Unity game through explicit game-owned commands.

```text
MCP client
  -> stdio JSON-RPC
  -> GameRuntimeMcpHost
  -> token-authenticated 127.0.0.1 RPC
  -> GameRuntimeMcpBridge
  -> SampleGamePlayActionHandler
```

The host owns transport only. The Unity game remains authoritative for state, legal actions, movement, interaction, and chat.

## Files

| File | Purpose |
|---|---|
| [`Runtime/GameRuntimeMcpBridge.cs`](Runtime/GameRuntimeMcpBridge.cs) | Loopback listener, session descriptor, token authentication, bounded main-thread dispatch |
| [`Runtime/SampleGamePlayActionHandler.cs`](Runtime/SampleGamePlayActionHandler.cs) | State, surroundings, movement, interaction, and chat sample |
| [`Runtime/SampleRuntimeMcpInteractable.cs`](Runtime/SampleRuntimeMcpInteractable.cs) | Explicit interaction interface and sample implementation |
| [`game-runtime.tools.json`](game-runtime.tools.json) | MCP tool schemas and RPC command mappings |
| [`Tests/GameRuntimeMcpBridgeTests.cs`](Tests/GameRuntimeMcpBridgeTests.cs) | PlayMode round-trip coverage |

## Choose one Unity adapter sample

This directory is an alternative to [`../unity`](../unity). Do not enable both bridges in the same runtime path.

- `examples/unity`: minimal bridge plus optional generic diagnostics
- `examples/unity-gameplay`: registered game-command bridge plus gameplay sample

## Tools

- `runtime_status` -> `runtime.status`
- `get_game_state` -> `game.get_state`
- `get_surroundings` -> `game.get_surroundings`
- `player_move_to` -> `player.move_to`
- `player_interact` -> `player.interact`
- `send_in_game_chat` -> `chat.send`

## Setup

1. Copy `Runtime` into the Unity project.
2. Add `GameRuntimeMcpBridge` to an explicit runtime-services object.
3. Add `SampleGamePlayActionHandler` to the controlled entity.
4. Assign `Controlled Entity`.
5. Optionally add `SampleRuntimeMcpInteractable` to a nearby object with a Collider.
6. Install and start the host:

```powershell
python -m pip install -e .

game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\unity-gameplay\game-runtime.tools.json
```

The runtime writes `game-runtime-mcp-session.json` under `Application.persistentDataPath`.

Custom handlers must return `[Serializable]` DTO classes with public fields that Unity `JsonUtility` can serialize. Anonymous or property-only return objects are outside this sample contract.

## Codex project-local skill

```powershell
& "C:\path\to\GameRuntimeMcpHost\skills\install-codex.ps1" `
  -TargetProject "C:\path\to\YourUnityProject"
```

Open a new Codex session after installation.

## Recommended low-reasoning order

```text
runtime_status
  -> get_game_state
  -> get_surroundings
  -> player_move_to
  -> get_game_state until movement is verified
  -> get_surroundings to refresh the target
  -> player_interact
  -> verify authoritative state
```

Use `targetId` returned by `get_surroundings` before falling back to `targetName`.

## Boundaries

- Desktop runtime with `HttpListener` support; WebGL is excluded by the assembly definition
- Numeric loopback only
- Per-run unlogged token
- Bounded request body, timeout, and per-frame dispatch
- No `Thread.Abort`
- No arbitrary C# execution
- Interaction requires an explicit `IGameRuntimeMcpInteractable`
- Chat is limited to 500 characters
- Movement distance and surroundings results are bounded

The sample uses direct Transform movement and 3D Physics. Replace sample state and actions with the project's authoritative services before production use.
