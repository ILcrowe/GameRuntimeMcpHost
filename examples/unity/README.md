# Unity runtime MCP sample

[한국어 가이드](README.ko.md)

Copy-ready Unity Player adapter with one bridge for transport, command registration, generic diagnostics, and game-owned actions.

## Structure

```text
MCP client
  -> stdio JSON-RPC
  -> GameRuntimeMcpHost
  -> token-authenticated 127.0.0.1 HTTP RPC
  -> GameRuntimeMcpBridge
     ├─ runtime status and diagnostics
     └─ registered game commands
          -> SampleGameRuntimeHandler
```

## Files

| File | Purpose |
|---|---|
| `Runtime/GameRuntimeMcpBridge.cs` | Session, token, listener, main-thread queue, command registry, diagnostics |
| `Runtime/SampleGameRuntimeHandler.cs` | State, surroundings, movement, interaction, chat |
| `Runtime/SampleRuntimeMcpInteractable.cs` | Inspector-attachable interaction sample |
| `game-runtime.tools.json` | MCP tool schemas and Unity RPC command mappings |
| `Tests/GameRuntimeMcpTests.cs` | PlayMode round-trip coverage |

`SampleRuntimeMcpInteractable` remains a separate file because an Inspector-attachable Unity `MonoBehaviour` needs a matching script file name.

## Setup

1. Copy `Runtime` into the Unity project.
2. Add `GameRuntimeMcpBridge` to a runtime-services object.
3. Add `SampleGameRuntimeHandler` to the controlled entity.
4. Assign `Controlled Entity`.
5. Add a Collider and `SampleRuntimeMcpInteractable` to a nearby test object.
6. Install and start the host.

```powershell
python -m pip install -e .

game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product UnityGameRuntime `
  --tools-file C:\path\to\GameRuntimeMcpHost\examples\unity\game-runtime.tools.json
```

## Tools

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

## Game command registration

```csharp
bindingList = new[]
{
    GameRuntimeMcpBridge.Bind(
        "inventory.get_state",
        HandleGetInventory),
    GameRuntimeMcpBridge.Bind(
        "inventory.use_item",
        HandleUseItem)
};

bridge.RegisterAll(this, out string error, bindingList);
```

Cleanup:

```csharp
bridge.UnregisterAll(this);
```

Results:

```csharp
return GameRuntimeMcpBridge.RuntimeCommandResult.Ok(data);
```

```csharp
return GameRuntimeMcpBridge.RuntimeCommandResult.Fail(
    "inventory_unavailable",
    "Inventory is unavailable.");
```

Keep related commands in one handler while they share dependencies and lifetime. Split only at a real service, authority, or lifecycle boundary.

## Recommended low-reasoning order

```text
runtime_status
-> runtime_build_info when build identity matters
-> get_game_state
-> get_surroundings
-> player_move_to
-> get_game_state until movement completes
-> get_surroundings to refresh target identity
-> player_interact
-> verify authoritative game state
```

## Boundaries

- Numeric loopback only
- Per-run unlogged token
- Bounded request body, timeout, and per-frame dispatch
- Main-thread game command execution
- Distinct timeout-before-start and execution-unknown responses
- No `Thread.Abort`
- No arbitrary runtime C# execution
- No remote binding or game-file browsing
- Adapter-controlled screenshot directory
- Game-owned legal-action validation and authoritative mutation

## Tests

```powershell
python -m unittest discover -s tests -v
```

Unity PlayMode test:

```text
GameRuntimeMcpTests.RuntimeToolsRoundTripThroughOneBridge
```

## A/B test

Compare low and high reasoning with the same request:

```text
tool selection
call count
invented tool names
read-before-write
verification-after-write
unsafe retry after timeout
final state match
```
