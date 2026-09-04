# Tool input schema validation

GameRuntimeMcpHost validates `tools/call` arguments against each tool manifest `inputSchema` before forwarding the request to the runtime.

```text
MCP client
-> tools/call
-> host argument validation
   -> failure: JSON-RPC -32602
   -> success: runtime RPC
```

The host validates structure, JSON types, and declared bounds. The game-owned runtime adapter still owns authorization, legal-action checks, current-state checks, and authoritative mutation.

## Supported dependency-free subset

```text
type
properties
required
additionalProperties
items
enum
minimum / maximum
exclusiveMinimum / exclusiveMaximum
minLength / maxLength
minItems / maxItems
anyOf
```

Accepted annotations:

```text
$schema / $id
title / description / default / examples
deprecated / readOnly / writeOnly
```

A manifest using an unsupported schema keyword fails during host construction instead of silently dropping the constraint.

## Failure behavior

Invalid arguments return JSON-RPC error `-32602`. The runtime RPC is not called.

Schema validation does not approve gameplay. A numeric coordinate may pass the host while the game adapter still rejects it as blocked, out of turn, unauthorized, or otherwise illegal.
