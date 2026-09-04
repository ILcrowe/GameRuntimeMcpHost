# Optional runtime diagnostics contract

`GameRuntimeMcpHost` remains transport-only. Generic diagnostics are optional, read-mostly observations exposed by the game-owned adapter through its existing tool manifest.

The unified Unity sample implements these diagnostics inside `GameRuntimeMcpBridge`. No second listener, session, token, or provider component.

## Tools

| MCP tool | Unity RPC | Purpose |
|---|---|---|
| `runtime_status` | `runtime.status` | Runtime, process, and scene state |
| `runtime_build_info` | `runtime.build_info` | Build and version identity |
| `runtime_logs_read` | `runtime.logs.read` | Bounded incremental logs |
| `runtime_metrics_snapshot` | `runtime.metrics.snapshot` | One performance snapshot |
| `runtime_capture_screenshot` | `runtime.capture_screenshot` | Adapter-controlled visual capture |

- Diagnostics-only manifest: `examples/runtime-diagnostics.tools.json`
- Unified Unity manifest: `examples/unity/game-runtime.tools.json`

## Boundaries

- Read-mostly observation
- No gameplay authority
- No replacement for game-owned state tools
- No arbitrary runtime C#
- No session token output
- Bounded log ring buffer
- Bounded metrics snapshot
- Adapter-controlled screenshot path

## Build identity

Recommended result:

```json
{
  "product": "ExampleGame",
  "version": "0.1.0",
  "unityVersion": "6000.x",
  "buildId": "stable-build-id",
  "developmentBuild": true,
  "platform": "WindowsPlayer",
  "scriptingBackend": "IL2CPP",
  "sourceRevision": "optional",
  "processId": 1234
}
```

`sourceRevision` is optional build-pipeline metadata.

## Incremental logs

```text
first call: sinceSequence = 0
next call: sinceSequence = previous nextSequence
continue: hasMore == true
```

Signals:

- `truncated`: requested history already dropped from the ring buffer
- `cursorReset`: cursor belongs to an older/different runtime sequence
- `nextSequence`: next cursor
- `newestSequence`: newest sequence at request time

Filtered entries advance the cursor only across inspected records. A page never skips uninspected records beyond its limit.

## Metrics

One low-cost current-frame snapshot for performance questions and before/after comparison.

## Screenshot

Generated under an adapter-controlled directory below `Application.persistentDataPath`.

`queued = true` means capture scheduling, not guaranteed file-write completion.

## Priority

```text
exact game-owned state/action tool
-> necessary generic diagnostic
-> capability missing
```
