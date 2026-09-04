# Unity runtime diagnostics provider

`UnityRuntimeDiagnosticsProvider` is an optional, explicit component for built Player observation.

It does not start a second transport, does not replace the game-owned runtime adapter, and does not contain gameplay commands.

## Provided observations

- `ReadBuildInfo()` — product/version/build GUID/engine/platform/backend/process identity.
- `ReadLogs()` — bounded incremental Unity logs with sequence cursors.
- `ReadMetricsSnapshot()` — one cheap frame/memory snapshot.
- `CaptureScreenshot()` — queues one screenshot under `Application.persistentDataPath`.

## Integration shape

The game-owned adapter remains responsible for its RPC dispatch. Map the optional diagnostic RPC commands to this provider:

```text
runtime.build_info
  -> diagnostics.ReadBuildInfo()

runtime.logs.read
  -> diagnostics.ReadLogs(request)

runtime.metrics.snapshot
  -> diagnostics.ReadMetricsSnapshot()

runtime.capture_screenshot
  -> diagnostics.CaptureScreenshot()
```

The included `UnityRuntimeMcpSampleBridge` already maps these commands when an enabled provider is attached to the same GameObject or assigned in the Inspector.

Do not create a second listener for diagnostics. Reuse the same runtime adapter/session/token already used by the game.

## Log behavior

`ReadLogs()` uses a bounded ring buffer.

- pass the previous `nextSequence` back as `sinceSequence`
- continue while `hasMore` is true
- use `limit` to bound each result page
- use `level` / `contains` before asking for more data
- request stack traces only when required

Cursor fields:

| Field | Meaning |
|---|---|
| `oldestSequence` | Oldest entry still retained by the ring buffer |
| `newestSequence` | Newest entry captured when the call was processed |
| `nextSequence` | Cursor to pass into the next call |
| `truncated` | The requested cursor was older than retained data |
| `hasMore` | Additional uninspected entries remain after this page |
| `cursorReset` | The supplied cursor was ahead of this runtime and the read restarted from retained data |

Filtered-out entries that were inspected advance `nextSequence`; entries beyond the page boundary are not skipped. After `cursorReset`, re-check runtime/build identity before interpreting logs as part of the previous process.

## Screenshot behavior

The caller does not choose a filesystem path. The provider creates a generated filename inside an adapter-controlled directory under `Application.persistentDataPath`.

The return value means the capture was queued; the image file may be written after the current frame.

## Build revision

Unity does not provide the source-control revision automatically. Set the component's optional `sourceRevision` from the project's build pipeline if source revision matching is required.
