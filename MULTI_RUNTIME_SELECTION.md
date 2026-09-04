# Multiple runtime selection

Use explicit session selectors when several players, clients, or servers from the same product run on one machine.

## Session search

Without a wildcard, `--session-name game-runtime-mcp-session.json` searches both:

```text
game-runtime-mcp-session.json
game-runtime-mcp-session-*.json
```

Without selectors, backward-compatible behavior remains: the newest matching product descriptor wins.

## Instance and role selectors

A game-owned adapter may publish:

```json
{
  "product": "ExampleGame",
  "instanceId": "client-01",
  "role": "client"
}
```

Host registration:

```powershell
game-runtime-mcp-host `
  --session-name game-runtime-mcp-session.json `
  --session-product ExampleGame `
  --session-instance client-01 `
  --session-role client `
  --tools-file C:\path\to\game-runtime.tools.json
```

Environment variables:

```text
GAME_RUNTIME_MCP_SESSION_INSTANCE
GAME_RUNTIME_MCP_SESSION_ROLE
```

## Unity sample

The bundled bridge already exposes `SessionFileName`. Assign a unique file name before `Start`:

```csharp
bridge.SessionProductName = "ExampleGame";
bridge.SessionFileName =
    "game-runtime-mcp-session-client-01.json";
```

`--session-instance client-01` can match the `-client-01` file-name suffix even when the descriptor does not publish `instanceId`.

`--session-role` requires a descriptor `role` field. A game can either encode the role in the instance ID or extend its owned descriptor metadata.

After attachment, verify the target through `runtime_status` before mutation.
