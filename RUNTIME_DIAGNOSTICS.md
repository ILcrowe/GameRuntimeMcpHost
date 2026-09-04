# Optional Runtime Diagnostics Contract

GameRuntimeMcpHost remains a transport layer. This document defines optional, game-independent runtime diagnostics that a game-owned adapter may expose through the existing tool manifest.

No CLI layer is required. These are ordinary MCP tools forwarded by GameRuntimeMcpHost to the connected Player adapter.

## Why this contract exists

Gameplay commands should remain explicit and game-owned. A small diagnostic surface is still useful for connection checks, build freshness, logs, performance, and visible-output verification without adding one-off gameplay tools.

Recommended optional tools:

| MCP tool | RPC command | Purpose |
|---|---|---|
| `runtime_status` | `runtime.status` | Runtime/process liveness and identity |
| `runtime_build_info` | `runtime.build_info` | Build/version identity |
| `runtime_logs_read` | `runtime.logs.read` | Bounded incremental logs |
| `runtime_metrics_snapshot` | `runtime.metrics.snapshot` | Bounded runtime performance snapshot |
| `runtime_capture_screenshot` | `runtime.capture_screenshot` | One visual verification capture |

The generic contract manifest is [`examples/runtime-diagnostics.tools.json`](examples/runtime-diagnostics.tools.json). The copy-ready Unity sample publishes the same diagnostics in [`examples/unity/unity-runtime-sample.tools.json`](examples/unity/unity-runtime-sample.tools.json).

A runtime adapter must implement a listed RPC command before publishing its MCP tool.

## Boundaries

- Diagnostics are read-mostly observation tools.
- Gameplay authority stays in game-specific commands.
- Runtime arbitrary-code execution is intentionally not part of this baseline.
- Session tokens must never appear in diagnostic output.
- Logs must be bounded and incrementally readable.
- Screenshots must use an adapter-controlled diagnostics directory unless a stricter game-owned contract says otherwise.
- Metrics are bounded snapshots, not unbounded streaming.

## Suggested result contracts

### `runtime.build_info`

```json
{
  "product": "ExampleGame",
  "version": "0.1.0",
  "engineVersion": "6000.x",
  "buildId": "stable-build-id",
  "developmentBuild": true,
  "platform": "WindowsPlayer",
  "scriptingBackend": "IL2CPP",
  "sourceRevision": "optional",
  "processId": 1234
}
```

### `runtime.logs.read`

```json
{
  "entries": [
    {
      "sequence": 42,
      "timestampUtc": "2026-09-04T00:00:00.0000000Z",
      "level": "error",
      "message": "bounded message",
      "stackTrace": ""
    }
  ],
  "oldestSequence": 1,
  "newestSequence": 48,
  "nextSequence": 42,
  "truncated": false,
  "hasMore": true,
  "cursorReset": false
}
```

The adapter owns ring-buffer size and message bounds.

- Send the previous `nextSequence` as the next `sinceSequence`.
- Continue while `hasMore` is true.
- `truncated` means the requested cursor predates the oldest retained entry.
- `cursorReset` means the supplied cursor was ahead of the current runtime sequence, normally after a process/session change; the adapter restarted the read from its current retained range.
- Filters may advance `nextSequence` across inspected non-matching entries, but a page must not skip uninspected entries beyond its limit.

### `runtime.metrics.snapshot`

Return only metrics that the adapter can collect cheaply and consistently. Keep the schema stable for before/after comparison.

### `runtime.capture_screenshot`

Return metadata and the generated file path. Do not send a large base64 image through the tool result by default, and do not accept an arbitrary caller-selected output path in the baseline contract.

## Unity provider

[`UnityRuntimeDiagnosticsProvider`](examples/unity/Runtime/UnityRuntimeDiagnosticsProvider.cs) implements build identity, bounded logs, a metrics snapshot, and an adapter-controlled screenshot path. The Unity sample bridge delegates the matching RPC commands to this optional component while retaining one listener/session/token.

## Skill routing

The repository includes a low-reasoning skill under [`skills/game-runtime-mcp-host/`](skills/game-runtime-mcp-host/).

Its fixed order is:

`target gate -> runtime status -> build identity -> exact game tool -> result/state verification -> optional diagnostics`
