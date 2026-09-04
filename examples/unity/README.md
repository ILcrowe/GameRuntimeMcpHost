# Unity C# runtime adapter sample

[한국어 가이드](README.ko.md)

This sample is the game-owned half of the GameRuntimeMcpHost connection. It opens a token-authenticated numeric-loopback endpoint, queues calls from its listener thread, and dispatches Unity work on the main thread.

## Requirements

- Unity 2022.3 LTS or newer
- A desktop target with `HttpListener` support; WebGL is excluded
- Python 3.10 or newer for GameRuntimeMcpHost

The sample uses only Unity and .NET APIs. It does not require a JSON package or Unity CLI.

## Setup

1. Copy [`Runtime`](Runtime) into your Unity project's `Assets/GameRuntimeMcpHostSample/Runtime` folder.
2. Add `UnityRuntimeMcpSampleBridge` to a visible `RuntimeServices` GameObject in the boot scene or a boot prefab.
3. Add `UnityRuntimeDiagnosticsProvider` to the same object when generic runtime diagnostics are wanted.
4. Enter Play Mode or run the built Player.
5. Start the host with the generated session descriptor and sample manifest:

```powershell
game-runtime-mcp-host `
  --session-file "C:\path\to\LocalLow\Company\Product\unity-runtime-mcp-sample.json" `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

The Unity log prints the exact session path after the listener starts. The descriptor is removed when the component stops.

For automatic `LocalLow` discovery, use the file name and Unity product name:

```powershell
game-runtime-mcp-host `
  --session-name unity-runtime-mcp-sample.json `
  --session-product YourUnityProductName `
  --tools-file "C:\path\to\GameRuntimeMcpHost\examples\unity\unity-runtime-sample.tools.json"
```

## Published sample tools

The sample manifest exposes:

| MCP tool | Purpose | Provider required |
|---|---|---|
| `runtime_status` | Runtime/process liveness | No |
| `runtime_build_info` | Build and process identity | `UnityRuntimeDiagnosticsProvider` |
| `runtime_logs_read` | Bounded incremental Unity logs | `UnityRuntimeDiagnosticsProvider` |
| `runtime_metrics_snapshot` | One cheap frame/memory snapshot | `UnityRuntimeDiagnosticsProvider` |
| `runtime_capture_screenshot` | Queue one screenshot under `persistentDataPath` | `UnityRuntimeDiagnosticsProvider` |
| `echo_message` | Main-thread transport round trip | No |

The generic diagnostics contract and cursor rules are documented in [`RUNTIME_DIAGNOSTICS.md`](RUNTIME_DIAGNOSTICS.md).

## Scene placement and lifetime

- Placement: `Boot Scene / RuntimeServices` or an equivalent boot prefab.
- Observation: components, port range, request limit, timeout, descriptor name, log capacity, and output directory remain visible in the Inspector.
- Lifetime: `OnEnable` starts/subscribes and `OnDisable` stops/unsubscribes. There is no hidden `RuntimeInitializeOnLoadMethod` bootstrap.
- Persistence: if the boot object must survive scene changes, make that an explicit responsibility of the existing boot/persistence system.

## Extending with game logic

1. Add a tool and JSON Schema to a game-owned tool manifest.
2. Add a typed payload DTO to the runtime adapter.
3. Add an RPC dispatch route.
4. Validate legal actions and revisions before mutating authoritative state.
5. Return a stable action/result identifier for retry-sensitive mutations.
6. Add a PlayMode round-trip test.

Generic diagnostics do not replace game-specific commands. Gameplay authority, legal-action validation, idempotency, and deterministic timeout recovery remain in the game adapter.

## Security boundaries

- Binding is fixed to numeric loopback `127.0.0.1`.
- A new unlogged token is generated for every bridge start.
- Requests use a bounded body, main-thread timeout, and per-frame dispatch budget.
- Unity APIs are called only by dispatch on the Unity main thread.
- Log messages, stack traces, and result collections are bounded.
- Screenshot output stays under an adapter-controlled directory in `Application.persistentDataPath`.
- The bridge does not provide arbitrary C# execution, file browsing, remote binding, or provider SDK access.
- Do not commit, upload, or log the generated session descriptor because it contains the active token.

For a shipping game, keep these components disabled or excluded unless runtime AI control is an intentional product feature.

## Automated sample test

Copy both `Runtime` and `Tests` into a Unity project with the Test Framework installed, then run the PlayMode test `UnityRuntimeMcpSampleBridgeTests`.

It verifies:

- descriptor creation and cleanup
- token rejection
- authenticated runtime status
- build identity
- filtered incremental log reading
- metrics snapshot
- main-thread echo

Screenshot file completion is intentionally not asserted because capture is queued for a later frame and may depend on the test runner's graphics environment.

## Design notes

The MCP protocol stays in the Python sidecar so a game build does not need to track MCP revisions. The Unity adapter owns only a small localhost RPC contract and game authority. The optional diagnostics provider reuses the same listener, session, and token; it does not create a second host or transport.
