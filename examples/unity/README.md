# Unity C# runtime adapter sample

[한국어 가이드](README.ko.md)

This sample is the game-owned half of the GameRuntimeMcpHost connection. It opens a token-authenticated numeric-loopback endpoint, queues calls from its listener thread, and dispatches Unity work on the main thread.

## Requirements

- Unity 2022.3 LTS or newer
- A desktop target with `HttpListener` support; WebGL is excluded
- Python 3.10 or newer for GameRuntimeMcpHost

The sample uses only Unity and .NET APIs. It does not require a JSON package.

## Three-step setup

1. Copy [`Runtime`](Runtime) into your Unity project's `Assets/GameRuntimeMcpHostSample/Runtime` folder.
2. Add `UnityRuntimeMcpSampleBridge` to a visible `RuntimeServices` GameObject in the boot scene or a boot prefab, then enter Play Mode.
3. Start the host with the generated session descriptor and this sample's manifest:

```powershell
game-runtime-mcp-host `
  --session-file "C:\path\to\LocalLow\Company\Product\unity-runtime-mcp-sample.json" `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

The Unity Console prints the exact session path after the listener starts. The descriptor is removed when the component stops.

For automatic `LocalLow` discovery, use the file name and the Unity product name:

```powershell
game-runtime-mcp-host `
  --session-name unity-runtime-mcp-sample.json `
  --session-product YourUnityProductName `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

The MCP client will expose `runtime_status` and `echo_message`.

## Scene placement and lifetime

- Placement: `Boot Scene / RuntimeServices` or an equivalent boot prefab.
- Observation: the component, port range, request limit, timeout, and descriptor name remain visible in the Inspector.
- Lifetime: `OnEnable` starts the bridge in Play Mode and `OnDisable` stops it. There is no hidden `RuntimeInitializeOnLoadMethod` bootstrap.
- Persistence: if the boot object must survive scene changes, make that an explicit responsibility of your existing boot/persistence system.

## Extending the sample

1. Add a tool and JSON Schema to `unity-runtime-sample.tools.json`.
2. Add typed payload fields or a payload DTO in `UnityRuntimeMcpSampleBridge.cs`.
3. Add a `switch` case in `Dispatch` and validate game rules before mutating authoritative state.

The sample's `runtime.status` and `sample.echo` commands are intentionally harmless. Real commands must implement authorization beyond observational `clientName`, idempotency for retryable mutations, legal-action checks, and a deterministic timeout fallback.

## Security boundaries

- Binding is fixed to numeric loopback `127.0.0.1`.
- A new unlogged token is generated for every bridge start.
- Requests use a bounded body, main-thread timeout, and per-frame dispatch budget.
- Unity APIs are called only by `Dispatch` on the Unity main thread.
- The bridge does not provide arbitrary C# execution, file browsing, remote binding, or provider SDK access.
- Do not commit, upload, or log the generated session descriptor because it contains the active token.

For a shipping game, keep the component disabled or excluded unless runtime AI control is an intentional product feature.

## Automated sample test

Copy both `Runtime` and `Tests` into a Unity project with the Test Framework installed, then run the PlayMode test `UnityRuntimeMcpSampleBridgeTests`. It verifies descriptor creation, authenticated `runtime.status`, main-thread `sample.echo`, and descriptor cleanup.

## Design notes

The MCP protocol stays in the Python sidecar so a game build does not need to track MCP revisions. The Unity adapter owns only a small localhost RPC contract and game authority. An explicit scene component was chosen over automatic bootstrap so release inclusion, configuration, and lifetime remain visible.
